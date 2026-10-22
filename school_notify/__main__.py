"""school-notify: push notifications for Webtop (SmartSchool) and Galim Pro.

  python -m school_notify setup-webtop        browser login once (parent account)
  python -m school_notify setup-galim         browser login once (student's ministry login)
  python -m school_notify galim-login-test    check that the unattended Galim login works
  python -m school_notify telegram-chat-id --token <bot token>
  python -m school_notify test-notify         send a test message to every channel
  python -m school_notify poll [--dry-run]    one round
  python -m school_notify run                 poll forever (what the service runs)
  python -m school_notify status              health, last fetch, recent notifications

All files live in ./data (or --data DIR / $SCHOOL_NOTIFY_DATA).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from . import galim, notify, poller, setup
from .store import Store, data_dir


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def flush_pending(store, quiet_ok=False):
    """Send queued notifications unless it is quiet time; keep what failed."""
    state, opts = store.state, store.options
    pending = state.setdefault("pending", [])
    if not pending or (not quiet_ok and poller.in_quiet_hours(opts.get("quiet_hours"))):
        return
    left = []
    for n in pending:
        if notify.deliver(store.config.get("notify") or [], n, log):
            recent = state.setdefault("recent", [])
            recent.append({"at": datetime.now().isoformat(timespec="seconds"), "title": n["title"], "body": n["body"][:120]})
            del recent[:-20]
        else:
            left.append(n)
    state["pending"] = left[-200:]


def one_round(store, only=None, dry_run=False):
    found = poller.poll(store, only=only, log=log)
    for n in found:
        log(f"{'would send' if dry_run else 'new'}: {n['title']} | {n['body'].replace(chr(10), ' / ')[:150]}")
    if dry_run:
        return found
    store.state.setdefault("pending", []).extend(found)
    flush_pending(store)
    store.state["last_poll"] = datetime.now().isoformat(timespec="seconds")
    store.save_state()
    return found


def cmd_setup_webtop(args, store):
    cred, token = setup.capture_webtop(timeout=args.timeout, log=log)
    store.config["webtop"] = cred
    store.state.setdefault("webtop", {})["token"] = token
    store.state.get("status", {}).pop("webtop", None)
    store.save_config()
    store.save_state()
    log(f"Saved to {store.config_path}")


def cmd_import_webtop(args, store):
    """Manual fallback: credential JSON on stdin (bio_login, unique_id, selected_user)."""
    raw = json.load(sys.stdin)
    cred, token = setup._verify_webtop(
        [raw.get("bio_login")], [raw.get("unique_id")], [raw.get("selected_user") or "", ""], [raw.get("device_id") or ""], log
    )
    store.config["webtop"] = cred
    store.state.setdefault("webtop", {})["token"] = token
    store.save_config()
    store.save_state()
    log(f"Saved to {store.config_path}")


def cmd_setup_galim(args, store):
    cred, cookie = setup.capture_galim(timeout=args.timeout, log=log)
    store.config["galim"] = cred
    gs = store.state.setdefault("galim", {})
    gs["cookie"] = cookie
    gs.pop("login", None)  # clears a previous wrong-password stop
    store.state.get("status", {}).pop("galim", None)
    store.save_config()
    store.save_state()
    log(f"Saved to {store.config_path}")


def cmd_galim_login_test(args, store):
    cred = store.config.get("galim")
    if not cred:
        sys.exit("no Galim login saved; run setup-galim first")
    gs = store.state.setdefault("galim", {})
    try:
        cookie = galim.guarded_login(cred, gs)
    except galim.GalimError as err:
        store.save_state()
        sys.exit(f"unattended Galim login failed: [{err.code}] {err}")
    gs["cookie"] = cookie
    store.save_state()
    found = galim.tasks(cookie)
    log(f"Unattended Galim login works ({sum(not t['done'] for t in found)} open tasks).")


def cmd_telegram(args, store):
    chats = notify.telegram_chat_ids(args.token)
    if not chats:
        sys.exit("No chats yet. Open the bot in Telegram, press Start (or send it any message), then run this again.")
    for chat_id, name in chats:
        print(f"{chat_id}\t{name}")


def cmd_test_notify(args, store):
    channels = store.config.get("notify") or []
    if not channels:
        sys.exit('no channel in config.json "notify" yet')
    n = poller.note("test", "test", "🔔 בדיקה: התראות בית הספר", "אם ההודעה הזו הגיעה, ההתראות מוגדרות נכון.", poller.WEBTOP_URL)
    ok = notify.deliver(channels, n, log)
    log("sent" if ok else "every channel failed")
    sys.exit(0 if ok else 1)


def cmd_poll(args, store):
    if args.preview:  # pretend nothing was seen yet, to see what the messages look like
        store.state.update(seen={}, seeded=["homework", "lesson_events", "messages", "galim_tasks"])
    one_round(store, only=args.only, dry_run=args.dry_run or args.preview)


def cmd_run(args, store_dir):
    log("school-notify running")
    while True:
        try:
            with Store(store_dir).lock():
                store = Store(store_dir)  # re-read under the lock (setup may have changed it)
                minutes = max(10, int(store.options.get("poll_minutes", 30)))
                one_round(store)
        except Exception as err:  # keep the service alive; the next round tries again
            log(f"round failed: {type(err).__name__}: {err}")
            minutes = 30
        time.sleep(minutes * 60)


def cmd_status(args, store):
    st, cfg = store.state, store.config
    print(f"data: {store.dir}")
    print(f"sources: {', '.join(k for k in ('webtop', 'galim') if k in cfg) or 'none'}; "
          f"channels: {', '.join(c.get('type', '?') for c in cfg.get('notify') or []) or 'none'}")
    print(f"last poll: {st.get('last_poll', 'never')}")
    for source, s in (st.get("status") or {}).items():
        print(f"  {source}: {'ok' if s.get('ok') else 'FAILING [' + str(s.get('code')) + '] ' + str(s.get('error'))}; last ok {s.get('last_ok', 'never')}")
    if st.get("galim", {}).get("login", {}).get("stopped"):
        print("  galim: logins STOPPED after a wrong password - run setup-galim again")
    for kind, ids in (st.get("seen") or {}).items():
        print(f"  seen {kind}: {len(ids)}")
    if st.get("pending"):
        print(f"pending (quiet hours or failed delivery): {len(st['pending'])}")
    for r in st.get("recent", [])[-10:]:
        print(f"  {r['at']}  {r['title']} | {r['body']}".replace("\n", " / "))


def main():
    parser = argparse.ArgumentParser(prog="school_notify", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", help="data directory (default: ./data next to the code, or $SCHOOL_NOTIFY_DATA)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("setup-webtop", "setup-galim"):
        sub.add_parser(name).add_argument("--timeout", type=int, default=480, help="seconds to wait for the login")
    sub.add_parser("import-webtop")
    sub.add_parser("galim-login-test")
    sub.add_parser("telegram-chat-id").add_argument("--token", required=True)
    sub.add_parser("test-notify")
    p = sub.add_parser("poll")
    p.add_argument("--dry-run", action="store_true", help="show what would be sent; save nothing")
    p.add_argument("--preview", action="store_true", help="dry run that shows everything currently there as if new")
    p.add_argument("--only", choices=("webtop", "galim"))
    sub.add_parser("run")
    sub.add_parser("status")
    args = parser.parse_args()

    directory = data_dir(args.data)
    if args.cmd == "run":
        return cmd_run(args, directory)
    with Store(directory).lock():
        store = Store(directory)
        {
            "setup-webtop": cmd_setup_webtop,
            "import-webtop": cmd_import_webtop,
            "setup-galim": cmd_setup_galim,
            "galim-login-test": cmd_galim_login_test,
            "telegram-chat-id": cmd_telegram,
            "test-notify": cmd_test_notify,
            "poll": cmd_poll,
            "status": cmd_status,
        }[args.cmd](args, store)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, galim.GalimError) as err:
        sys.exit(f"error: {err}")
    except KeyboardInterrupt:
        sys.exit(130)
