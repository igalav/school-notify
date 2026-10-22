"""Galim Pro client.

Galim Pro (pro.galim.org.il) has no public API. Its web app reads the student's
tasks from lms.galim.org.il/personal_api/tasks with a session cookie, and this
module makes the same call.

The session lasts ~8 hours. Login is the Ministry of Education SSO (הזדהות
אחידה, lgn.edu.gov.il) behind an F5 bot check that needs a real browser, so
logging in again runs headless Chromium through Playwright with the student's
ministry username and password. To protect the student's account the poller
logs in at most once per 10 minutes, backs off on failures, and stops
completely on a wrong password until setup-galim is run again.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

TASKS_URL = "https://lms.galim.org.il/personal_api/tasks"
ORIGIN = "https://pro.galim.org.il"
LOGIN_URL = "https://userdata.galim.org.il/login_idm"
LMS_COOKIES = ("SID", "LMSAffinity", "LMSAffinityCORS")
# A plain desktop Chrome UA (no "HeadlessChrome", which bot filters flag).
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_TASKS = 40

# Error text shown by the ministry login page -> stable code.
LOGIN_ERRORS = {
    "אחד או יותר מפרטי ההזדהות שגויים": ("bad_credentials", "wrong username or password"),
    "חשבונך חסום": ("bad_credentials", "account disabled"),
    "ננעל": ("bad_credentials", "account locked (too many attempts)"),
    "פג תוקף": ("bad_credentials", "password expired - the student must log in and change it"),
    "אני לא רובוט": ("bot_check", "the login page asked for a captcha"),
}


class GalimError(Exception):
    """`code`: login_expired, bad_credentials, bot_check, unexpected_page, timeout,
    galim_down, network, no_playwright, waiting (login postponed by the pacing rules)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _fetch(cookie, completed):
    # The same body the web app sends; a missing filterData field makes the server answer 500.
    body = {
        "page": 0,
        "filterData": {
            "completedActive": completed,
            "selfActive": False,
            "orderBy": "assignDateOrder",
            "class": -1,
            "field": -1,
            "checkType": -1,
            "unit_type": -1,
            "grade_display": -1,
            "targetDateOrder": False,
            "newSubmittedOrder": False,
            "assignDateOrder": 1,
            "nameOrder": False,
        },
        "limit": MAX_TASKS,
    }
    req = urllib.request.Request(
        TASKS_URL,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "Cookie": cookie,
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise GalimError("login_expired", "Galim session expired") from err
        raise GalimError("galim_down", f"Galim answered HTTP {err.code}") from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise GalimError("network", f"Galim unreachable: {getattr(err, 'reason', err)}") from err
    try:
        data = json.loads(raw)
    except ValueError as err:
        # A dead session can also come back as the login page.
        raise GalimError("login_expired", "Galim session expired") from err
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise GalimError("galim_down", "unexpected answer from Galim")
    if not data.get("userdata"):
        raise GalimError("login_expired", "Galim session expired")
    return data["tasks"]


def _slim(task):
    d = (task.get("task_lookup") or {}).get("data") or {}
    return {
        "id": task.get("_id"),
        "name": d.get("name") or d.get("unit_name") or "",
        "field": d.get("field") or "",
        "url": d.get("url") or "",
        "comment": d.get("comment") or "",
        "start": d.get("start_date"),
        "due": d.get("target_date") or task.get("last_target_date"),
        "done": bool(task.get("isCompleted")),
        "grade": task.get("grade"),
    }


def tasks(cookie):
    """Open and submitted tasks, slimmed, deduplicated."""
    seen, out = set(), []
    for t in _fetch(cookie, False) + _fetch(cookie, True):
        s = _slim(t)
        if s["id"] and s["id"] not in seen:
            seen.add(s["id"])
            out.append(s)
    return out


# ---------------------------------------------------------------- login
def _classify(text):
    for needle, mapped in LOGIN_ERRORS.items():
        if needle in (text or ""):
            return mapped
    return None


def _sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as err:
        raise GalimError("no_playwright", "Playwright is not installed (pip install playwright; playwright install chromium)") from err
    return sync_playwright


def cookie_header(cookies):
    present = [c for c in cookies if c["name"] in LMS_COOKIES]
    if not any(c["name"] == "SID" for c in present):
        return None
    return "; ".join(f"{c['name']}={c['value']}" for c in present)


def login(username, password):
    """Log in headless and return the lms cookie header, or raise GalimError."""
    sync_playwright = _sync_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        try:
            ctx = browser.new_context(
                locale="he-IL", timezone_id="Asia/Jerusalem", viewport={"width": 1366, "height": 850}, user_agent=UA
            )
            page = ctx.new_page()
            lms_calls = []
            page.on("request", lambda r: "lms.galim.org.il" in r.url and lms_calls.append(r.url))
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=40_000)
            try:
                page.wait_for_selector("#password", timeout=40_000)
            except Exception as err:
                raise GalimError("unexpected_page", "the ministry login form never appeared") from err
            # #password is read-only until focused: click, then type like a person.
            page.click("#userName")
            page.type("#userName", username, delay=35)
            page.click("#password")
            page.type("#password", password, delay=35)
            page.click("button[type=submit]")
            deadline = time.time() + 40
            while "pro.galim.org.il" not in page.url:
                if time.time() > deadline:
                    raise GalimError("timeout", "login did not finish within 40 s")
                page.wait_for_timeout(800)
                if "otp" in page.url.lower():
                    raise GalimError("unexpected_page", "the login asked for an SMS / OTP code")
                try:
                    hit = _classify(page.evaluate("document.body ? document.body.innerText : ''"))
                except Exception:
                    hit = None
                if hit:
                    raise GalimError(*hit)
            # Logged in; wait until the app has called lms.galim.org.il so its cookies exist.
            for _ in range(15):
                header = cookie_header(ctx.cookies())
                if header and lms_calls:
                    return header
                page.wait_for_timeout(700)
            header = cookie_header(ctx.cookies())
            if not header:
                raise GalimError("unexpected_page", "logged in, but Galim set no session cookie")
            return header
        finally:
            browser.close()


BACKOFF = [600, 1800, 3600, 10800]  # 10 min, 30 min, 1 h, then every 3 h
MIN_GAP = 600


def guarded_login(cred, gstate, now=None):
    """Log in unless the pacing rules say wait. Updates `gstate["login"]` in place."""
    now = now or time.time()
    ls = gstate.setdefault("login", {})
    fingerprint = _fingerprint(cred)
    if ls.get("stopped") and ls.get("fingerprint") == fingerprint:
        raise GalimError("bad_credentials", ls.get("detail") or "wrong username or password (run setup-galim again)")
    if ls.get("fingerprint") != fingerprint:  # new credentials: start clean
        ls.clear()
        ls["fingerprint"] = fingerprint
    if now - ls.get("last_attempt", 0) < MIN_GAP or now < ls.get("next_retry", 0):
        raise GalimError("waiting", "Galim login postponed (pacing / back-off)")
    ls["last_attempt"] = now
    try:
        header = login(cred["username"], cred["password"])
    except GalimError as err:
        if err.code == "bad_credentials":
            ls.update(stopped=True, detail=str(err))
        elif err.code != "no_playwright":
            i = min(ls.get("backoff", 0), len(BACKOFF) - 1)
            ls.update(next_retry=now + BACKOFF[i], backoff=i + 1)
        raise
    ls.update(backoff=0, next_retry=0, stopped=False)
    return header


def _fingerprint(cred):
    import hashlib

    return hashlib.sha256(f"{cred.get('username')}\0{cred.get('password')}".encode()).hexdigest()[:16]
