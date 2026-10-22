"""One polling round: fetch, compare with what was seen before, produce notifications.

The first successful round of each kind (homework, messages, lesson events,
Galim tasks) only records what is already there, so setting up doesn't flood
the phone with the whole term.
"""

from __future__ import annotations

import html
import re
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

from . import galim, webtop

KEEP_DAYS = 120  # forget seen ids after this long
WEBTOP_URL = "https://webtop.smartschool.co.il/"
GALIM_URL = "https://pro.galim.org.il/"
CREDENTIAL_ERRORS = {"credential_rejected", "bad_credentials"}


def ddmm(iso):
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%d/%m")
    except (TypeError, ValueError):
        return ""


def short(text, limit=300):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style")
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def to_text(markup):
    p = _Text()
    p.feed(markup or "")
    text = html.unescape("".join(p.parts)).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(" ".join(l.split()) for l in text.splitlines())).strip()


class Seen:
    """id -> ISO date last seen, per kind; `seeded` marks kinds past their first round."""

    def __init__(self, state, kind):
        self.map = state.setdefault("seen", {}).setdefault(kind, {})
        self.seeded_set = state.setdefault("seeded", [])
        self.kind = kind
        self.today = date.today().isoformat()

    @property
    def seeded(self):
        return self.kind in self.seeded_set

    def is_new(self, item_id):
        new = item_id not in self.map
        self.map[item_id] = self.today
        return new and self.seeded

    def finish(self):
        if not self.seeded:
            self.seeded_set.append(self.kind)
        cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        for key in [k for k, d in self.map.items() if d < cutoff]:
            del self.map[key]


def note(source, kind, title, body, url):
    return {"source": source, "kind": kind, "title": title, "body": body, "url": url}


def poll_webtop(cfg, opts, state, log, out):
    o = opts["webtop"]
    ws = state.setdefault("webtop", {})
    client = webtop.Webtop(cfg["webtop"], token=ws.get("token"))
    try:
        students = client.students()
        prefix = (lambda s: f"{s['first']}: ") if len(students) > 1 else (lambda s: "")
        today = date.today().isoformat()

        if o["homework"]:
            seen = Seen(state, "homework")
            for s in students:
                for week in (-1, 0):
                    for hw in client.homework(s, week):
                        if seen.is_new(hw["id"]):
                            when = f" (שיעור {ddmm(hw['date'])})" if hw["date"] and hw["date"] != today else ""
                            out.append(note("webtop", "homework", f"📚 {prefix(s)}שיעורי בית: {hw['subject']}{when}", short(hw["homework"]), WEBTOP_URL))
            seen.finish()

        if o["lesson_events"]:
            seen = Seen(state, "lesson_events")
            for s in students:
                for ev in client.lesson_events(s):
                    if seen.is_new(ev["id"]) and (o["attendance"] or ev["kind"] != 3):
                        icon = {1: "🌟", 3: "🚪"}.get(ev["kind"], "⚠️")
                        where = " · ".join(filter(None, [ev["subject"], ddmm(ev["date"]), f"שיעור {ev['hour']}" if ev["hour"] else ""]))
                        body = where + (f"\n{ev['remark']}" if ev["remark"] else "")
                        out.append(note("webtop", "lesson_event", f"{icon} {prefix(s)}{ev['event']}", body, WEBTOP_URL))
            seen.finish()

        if o["messages"]:
            seen = Seen(state, "messages")
            for msg in client.messages():
                if seen.is_new(msg["id"]):
                    body = msg["subject"]
                    if o["message_bodies"] and msg["message_id"]:
                        text = to_text(client.message_body(msg["message_id"]))  # marks it read on Webtop
                        body = f"{msg['subject']}\n\n{short(text, 1500)}" if text else body
                    elif msg["files"]:
                        body += " 📎"
                    out.append(note("webtop", "message", f"✉️ הודעה מ{msg['sender']}", body, WEBTOP_URL))
            seen.finish()
    finally:
        ws["token"] = client.token  # keep a working token for the next round


def poll_galim(cfg, opts, state, log, out):
    o = opts["galim"]
    gs = state.setdefault("galim", {})
    cookie = gs.get("cookie")
    found = None
    if cookie:
        try:
            found = galim.tasks(cookie)
        except galim.GalimError as err:
            if err.code != "login_expired":
                raise
            log("Galim session expired, logging in again")
    if found is None:
        if not cfg.get("galim", {}).get("password"):
            raise galim.GalimError("bad_credentials", "no Galim login saved (run setup-galim)")
        cookie = galim.guarded_login(cfg["galim"], gs)
        gs["cookie"] = cookie
        found = galim.tasks(cookie)

    tasks_seen = Seen(state, "galim_tasks")
    graded = state.setdefault("seen", {}).setdefault("galim_grades", {})
    first = not tasks_seen.seeded
    new_lines, grade_lines = [], []
    for t in found:
        if tasks_seen.is_new(t["id"]) and not t["done"] and o["new_tasks"]:
            due = ""
            if t["due"]:
                try:
                    due = f" (עד {datetime.fromisoformat(t['due'].replace('Z', '+00:00')).astimezone().strftime('%d/%m %H:%M')})"
                except ValueError:
                    pass
            new_lines.append(f"🆕 {t['name']}{due}")
        if t["grade"] is not None and str(t["id"]) not in graded:
            graded[str(t["id"])] = t["grade"]
            if not first and o["grades"]:
                grade_lines.append(f"✅ {t['name']}: ציון {t['grade']}")
    tasks_seen.finish()
    if new_lines:
        out.append(note("galim", "galim_task", "📘 גלים פרו: משימה חדשה" if len(new_lines) == 1 else "📘 גלים פרו: משימות חדשות", "\n".join(new_lines), GALIM_URL))
    if grade_lines:
        out.append(note("galim", "galim_grade", "📘 גלים פרו: ציון", "\n".join(grade_lines), GALIM_URL))
    gs["open"] = sum(not t["done"] for t in found)


def _status(state, source, ok, error=None, opts=None):
    """Track health; returns an alert notification when one is due."""
    st = state.setdefault("status", {}).setdefault(source, {})
    now = time.time()
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    name = {"webtop": "Webtop", "galim": "גלים פרו"}[source]
    if ok:
        alerted = st.get("alerted")
        st.update(ok=True, last_ok=stamp, error=None, code=None, failing_since=None, alerted=False)
        if alerted:
            return note(source, "health", f"✅ {name} חזר לעבוד", "ההתראות ממשיכות כרגיל.", None)
        return None
    st.update(ok=False, error=str(error), code=getattr(error, "code", "other"), last_error=stamp)
    if not st.get("failing_since"):
        st["failing_since"] = now
    if st.get("alerted") or getattr(error, "code", "") == "waiting":
        return None
    hours = (now - st["failing_since"]) / 3600
    if st["code"] in CREDENTIAL_ERRORS or hours >= opts["alert_after_hours"]:
        st["alerted"] = True
        fix = "צריך להתחבר מחדש (הריצו שוב את ההגדרה)." if st["code"] in CREDENTIAL_ERRORS else "בדקו שהמחשב מחובר לאינטרנט."
        return note(source, "health", f"⚠️ אין עדכונים מ{name}", f"{error}\n{fix}", None)
    return None


def poll(store, only=None, log=print):
    """Run one round for every configured source; returns the notifications."""
    cfg, state, opts = store.config, store.state, store.options
    out = []
    for source, fn in (("webtop", poll_webtop), ("galim", poll_galim)):
        if source not in cfg or (only and source != only):
            continue
        try:
            # Items are marked seen as they are read, so whatever was collected
            # before a failure part-way through must still be sent.
            fn(cfg, opts, state, log, out)
            alert = _status(state, source, True)
        except (webtop.WebtopError, galim.GalimError) as err:
            log(f"{source}: {err}")
            alert = _status(state, source, False, err, opts)
        if alert:
            out.append(alert)
    return out


def in_quiet_hours(spec, now=None):
    if not spec:
        return False
    now = (now or datetime.now()).strftime("%H:%M")
    start, end = [s.strip().zfill(5) for s in spec.split("-")]
    return start <= now < end if start <= end else now >= start or now < end
