"""Delivery channels. Each entry of config["notify"] is one channel:

  {"type": "ntfy", "topic": "...", "server": "https://ntfy.sh", "token": optional}
  {"type": "telegram", "bot_token": "...", "chat_id": "..."}
  {"type": "email", "host": "smtp.gmail.com", "port": 587, "username": "...",
   "password": "<app password>", "to": ["..."], "from": optional}
  {"type": "webhook", "url": "...", "headers": optional {...}}
  {"type": "command", "command": "..."}   # notification JSON on stdin, SN_TITLE / SN_BODY / SN_URL in env

A notification is {"source", "kind", "title", "body", "url"}.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import subprocess
import urllib.request
from email.message import EmailMessage


class NotifyError(Exception):
    pass


def _post_json(url, payload, headers=None, timeout=20):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as err:
        raise NotifyError(f"{type(err).__name__}: {getattr(err, 'reason', err)}") from err


def ntfy(ch, n):
    headers = {"Authorization": f"Bearer {ch['token']}"} if ch.get("token") else {}
    payload = {"topic": ch["topic"], "title": n["title"], "message": n["body"] or n["title"]}
    if n.get("url"):
        payload["click"] = n["url"]
    _post_json(ch.get("server", "https://ntfy.sh").rstrip("/"), payload, headers)


def telegram(ch, n):
    text = f"{n['title']}\n{n['body']}".strip()
    if n.get("url"):
        text += f"\n{n['url']}"
    _post_json(
        f"https://api.telegram.org/bot{ch['bot_token']}/sendMessage",
        {"chat_id": ch["chat_id"], "text": text[:4000], "disable_web_page_preview": True},
    )


def email(ch, n):
    msg = EmailMessage()
    msg["Subject"] = n["title"]
    msg["From"] = ch.get("from") or ch["username"]
    to = ch["to"] if isinstance(ch["to"], list) else [ch["to"]]
    msg["To"] = ", ".join(to)
    msg.set_content(f"{n['body']}\n\n{n.get('url') or ''}".strip())
    try:
        port = int(ch.get("port", 587))
        if port == 465:
            server = smtplib.SMTP_SSL(ch["host"], port, timeout=30, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(ch["host"], port, timeout=30)
            server.starttls(context=ssl.create_default_context())
        with server:
            server.login(ch["username"], ch["password"])
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as err:
        raise NotifyError(f"{type(err).__name__}: {err}") from err


def webhook(ch, n):
    _post_json(ch["url"], n, ch.get("headers"))


def command(ch, n):
    env = dict(os.environ, SN_TITLE=n["title"], SN_BODY=n["body"], SN_URL=n.get("url") or "", SN_KIND=n["kind"])
    try:
        done = subprocess.run(
            ch["command"], shell=True, input=json.dumps(n, ensure_ascii=False), text=True,
            env=env, capture_output=True, timeout=60,
        )
    except subprocess.TimeoutExpired as err:
        raise NotifyError("command timed out") from err
    if done.returncode != 0:
        raise NotifyError(f"command exited {done.returncode}: {done.stderr.strip()[:200]}")


CHANNELS = {"ntfy": ntfy, "telegram": telegram, "email": email, "webhook": webhook, "command": command}


def deliver(channels, n, log=print):
    """Send to every channel; True if at least one accepted it."""
    if not channels:
        log(f"[no channel configured] {n['title']} | {n['body']}")
        return True
    ok = False
    for ch in channels:
        send = CHANNELS.get(ch.get("type"))
        if not send:
            log(f"unknown notify type {ch.get('type')!r}")
            continue
        try:
            send(ch, n)
            ok = True
        except (NotifyError, KeyError) as err:
            log(f"{ch['type']}: delivery failed: {err}")
    return ok


def telegram_chat_ids(bot_token):
    """Chats that have messaged the bot recently: [(chat_id, name)]."""
    raw = _post_json(f"https://api.telegram.org/bot{bot_token}/getUpdates", {})
    out = {}
    for upd in json.loads(raw).get("result", []):
        chat = (upd.get("message") or upd.get("my_chat_member") or {}).get("chat") or {}
        if chat.get("id"):
            out[chat["id"]] = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
    return list(out.items())
