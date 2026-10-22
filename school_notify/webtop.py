"""Webtop (SmartSchool) client - standard library only.

Webtop has no public API. Its web app talks JSON to webtopserver.smartschool.co.il
with one cookie, `webToken`. Password login is reCAPTCHA-gated, but the site's
"remember me" (זכור אותי) registers a long-lived credential (~1 year) that
`user/loginByBio` turns into a fresh webToken with no password and no captcha.
`setup.py` captures that credential once from a real browser login.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request

BASE = "https://webtopserver.smartschool.co.il/server/api/"
ORIGIN = "https://webtop.smartschool.co.il"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Teachers often type "nothing" into the homework field instead of leaving it empty.
NO_HOMEWORK = {
    "אין", "אין שיעורי בית", "אין שעורי בית", "לא הוזן", "ללא", "ללא שיעורי בית",
    "none", "n/a", "-", "--", ".",
}


class WebtopError(Exception):
    """`code` is one of: credential_rejected, network, webtop_down, auth."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _Auth(Exception):
    """The token is dead (HTTP 401) or the server refused the call (status=false)."""


def clean(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


class Webtop:
    def __init__(self, cred, token=None, timeout=20):
        """`cred` = {"bio_login", "unique_id", "selected_user", "device_id", "is_mobile"}."""
        self.cred = cred
        self.token = token
        self.timeout = timeout
        self.logged_in = False  # logged in during this run

    # ------------------------------------------------------------ transport
    def _raw(self, path, payload):
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/plain, */*",
            "language": "he",
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "User-Agent": UA,
        }
        if self.token:
            headers["Cookie"] = f"webToken={self.token}"
        req = urllib.request.Request(
            BASE + path, data=json.dumps(payload or {}).encode(), method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 401:
                raise _Auth(path) from err
            raise WebtopError("webtop_down", f"{path}: HTTP {err.code}") from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise WebtopError("network", f"{path}: {getattr(err, 'reason', err)}") from err
        try:
            body = json.loads(raw)
        except ValueError as err:
            raise WebtopError("webtop_down", f"{path}: not JSON") from err
        if not isinstance(body, dict) or body.get("status") is not True:
            # Also what a stale session looks like (seen on InitDashboard), so log in again.
            raise _Auth(path)
        return body.get("data")

    def call(self, path, payload=None):
        """POST with the current token; on an auth failure log in once and retry."""
        if not self.token:
            self.login()
        try:
            return self._raw(path, payload)
        except _Auth:
            if self.logged_in:
                raise WebtopError("webtop_down", f"{path}: status=false") from None
            self.login()
            try:
                return self._raw(path, payload)
            except _Auth:
                raise WebtopError("webtop_down", f"{path}: status=false") from None

    def login(self):
        cred = self.cred
        self.token = None
        try:
            data = self._raw(
                "user/loginByBio",
                {
                    "id": cred["bio_login"],
                    "param1": "2",  # the remember-me path
                    "param2": cred.get("device_id", "") or "",
                    "param3": cred.get("selected_user", "") or "",
                    "param4": cred.get("unique_id", "") or "",
                    "param5": str(bool(cred.get("is_mobile", True))).lower(),
                },
            )
        except _Auth:
            raise WebtopError("credential_rejected", "Webtop refused the saved login (run setup-webtop again)") from None
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise WebtopError("credential_rejected", "Webtop refused the saved login (run setup-webtop again)")
        self.token = token
        self.logged_in = True

    # ------------------------------------------------------------ endpoints
    def students(self):
        data = self.call("dashboard/InitDashboard")
        rows = data.get("childrens") if isinstance(data, dict) else data  # sic
        out = []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("id") or row.get("classCode") is None:
                continue
            name = row.get("studentName") or f"{row.get('firstName') or ''} {row.get('lastName') or ''}".strip()
            out.append(
                {
                    "id": row["id"],
                    "name": clean(name),
                    "first": clean(row.get("firstName")) or clean(name).split(" ")[0],
                    "classCode": row["classCode"],
                    "studyYear": row.get("studyYear"),
                }
            )
        if not out:
            raise WebtopError("webtop_down", "no students on this account")
        return out

    def _pupil(self, student, module, week_index=0):
        return {
            "classCode": student["classCode"],
            "moduleID": module,
            "studentID": student["id"],
            "studentName": student["name"],
            "studyYear": student["studyYear"],
            "viewType": 0,
            "weekIndex": week_index,
        }

    def homework(self, student, week_index=0):
        """Homework of one week (0 = this week, -1 = last week)."""
        data = self.call("PupilCard/GetPupilLessonsAndHomework", self._pupil(student, 11, week_index))
        items = []
        for day in data if isinstance(data, list) else []:
            if not isinstance(day, dict):
                continue
            for hour in day.get("hoursData") or []:
                for entry in (hour or {}).get("scheduale") or []:  # sic
                    if not isinstance(entry, dict):
                        continue
                    text = entry.get("homeWork") if isinstance(entry.get("homeWork"), str) else ""
                    text = text.replace('\\"', '"').strip()  # Webtop leaves JSON escapes in the text
                    norm = " ".join(text.split()).strip(".!:;־-").casefold()
                    if not norm or norm in NO_HOMEWORK:
                        continue
                    item = {
                        "date": str(day.get("date") or "")[:10],
                        "subject": clean(entry.get("subject_name")) or "?",
                        "teacher": clean(entry.get("teacher")),
                        "homework": text,
                    }
                    # Same identity as the Home Assistant integration: an edited text is a new item.
                    key = "|".join([student["name"], item["subject"], text, item["date"]])
                    item["id"] = hashlib.md5(key.encode()).hexdigest()
                    items.append(item)
        return items

    def lesson_events(self, student):
        """The whole school year's lesson events (אירועי שיעור: praise, absences, remarks)."""
        data = self.call("PupilCard/GetPupilDiciplineEvents", self._pupil(student, 4))  # sic
        rows = (data or {}).get("diciplineEvents") or [] if isinstance(data, dict) else []
        out = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("eventType"):
                continue
            event = {
                "date": str(row.get("eventDate") or "")[:10],
                "hour": row.get("hourNum"),
                "subject": clean(row.get("subjectName")),
                "teacher": clean(row.get("teacherName")),
                "event": clean(row.get("eventType")),
                # 1 = positive (e.g. מילה טובה), 3 = attendance, 0 = other
                "kind": row.get("eventTypeId"),
                "remark": clean(row.get("remark")),
            }
            key = "|".join([student["name"], event["date"], str(event["hour"]), event["subject"], event["event"], event["remark"]])
            event["id"] = hashlib.md5(key.encode()).hexdigest()
            out.append(event)
        return out

    def messages(self, page=1):
        """One page of the account's inbox, newest first."""
        rows = self.call("messageBox/GetMessagesInbox", {"PageId": page, "LabelId": 0, "HasRead": None, "SearchQuery": ""})
        out = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            # student_F_name / student_L_name hold the *sender's* name.
            sender = f"{clean(row.get('student_L_name'))} {clean(row.get('student_F_name'))}".strip()
            msg = {
                "message_id": row.get("messageId"),
                "subject": clean(row.get("subject")),
                "sender": sender or clean(row.get("fromTitle")),
                "sent": str(row.get("sendingDate") or "")[:16].replace("T", " "),
                "files": bool(row.get("filesWereAttached")),
            }
            key = str(msg["message_id"] or f"{msg['subject']}|{msg['sender']}|{msg['sent']}")
            msg["id"] = hashlib.md5(key.encode()).hexdigest()
            out.append(msg)
        return out

    def message_body(self, message_id):
        """The full text of one message. Note: Webtop then marks it as read."""
        data = self.call(
            "messageBox/GetMessagesInboxData",
            {"MessageId": message_id, "FilterId": 0, "IsInbox": True, "hasRead": None},
        )
        return ((data or {}).get("messageData") or {}).get("messageContent") or ""
