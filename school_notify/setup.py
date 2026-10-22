"""One-time credential capture: a real browser window opens, the parent logs in as usual.

Nothing needs to be copied by hand from DevTools; the values are read from the
browser session and checked against the server before they are saved.
"""

from __future__ import annotations

import itertools
import json
import time

from . import galim, webtop

WEBTOP_LOGIN = "https://webtop.smartschool.co.il/account/login?device=1"

_IDB = """() => new Promise(done => {
  let req;
  try { req = indexedDB.open('WebTop'); } catch (e) { return done({}); }
  req.onerror = () => done({});
  req.onsuccess = () => {
    try {
      const store = req.result.transaction('storage', 'readonly').objectStore('storage');
      const out = {}, keys = ['bioLogin', 'deviceId', 'uniqueId'];
      let left = keys.length;
      keys.forEach(k => {
        const g = store.get(k);
        g.onsuccess = () => { out[k] = g.result; if (--left === 0) done(out); };
        g.onerror = () => { if (--left === 0) done(out); };
      });
    } catch (e) { done({}); }
  };
})"""


def _unquote(value):
    """localStorage values are sometimes JSON-encoded strings."""
    if isinstance(value, str):
        try:
            inner = json.loads(value)
            if isinstance(inner, str):
                return inner
        except ValueError:
            pass
        return value
    return value if isinstance(value, str) else None


def _browser(p):
    return p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])


def capture_webtop(timeout=600, log=print):
    sync_playwright = galim._sync_playwright()
    write_bio = []
    with sync_playwright() as p:
        browser = _browser(p)
        try:
            ctx = browser.new_context(locale="he-IL", viewport={"width": 1100, "height": 850})
            page = ctx.new_page()

            def on_request(req):
                if "writebio" in req.url.lower():
                    try:
                        write_bio.append(req.post_data_json or {})
                    except Exception:
                        write_bio.append({})

            ctx.on("request", on_request)
            page.goto(WEBTOP_LOGIN, wait_until="domcontentloaded", timeout=60_000)
            log(
                "A browser window is open on the Webtop login page.\n"
                "  1. Log in with your parent username and password.\n"
                "  2. IMPORTANT: tick 'זכור אותי' (remember me) before pressing login.\n"
                "  3. Solve the 'I'm not a robot' check if it shows up.\n"
                "The window closes by itself once the login is captured."
            )
            deadline = time.time() + timeout
            logged_in_at = None
            while time.time() < deadline:
                if page.is_closed():
                    break
                page.wait_for_timeout(1000)
                if write_bio:
                    page.wait_for_timeout(3000)  # let the app finish writing its storage
                    break
                if "/account/login" not in page.url and logged_in_at is None:
                    logged_in_at = time.time()
                if logged_in_at and time.time() - logged_in_at > 25:
                    break  # logged in, but no remember-me registration seen
            if page.is_closed():
                raise RuntimeError("the browser window was closed before the login finished")
            local = page.evaluate("() => Object.assign({}, localStorage)")
            idb = page.evaluate(_IDB) or {}
            cookies = {c["name"]: c["value"] for c in ctx.cookies() if "smartschool" in c["domain"]}
        finally:
            browser.close()

    if not write_bio and not local.get("SavedUser") and not idb.get("bioLogin") and not cookies.get("bioLogin"):
        raise RuntimeError(
            "logged in, but Webtop did not register a remember-me login. "
            "Run setup-webtop again and tick 'זכור אותי' before pressing login."
        )
    body = write_bio[-1] if write_bio else {}
    bios = [body.get("id"), _unquote(local.get("SavedUser")), _unquote(idb.get("bioLogin")), cookies.get("bioLogin")]
    uids = [_unquote(local.get("wt_uid")), _unquote(idb.get("uniqueId")), body.get("uniqueId"), body.get("param4")]
    selected = [_unquote(local.get("selectedUser")), ""]
    devices = ["", _unquote(idb.get("deviceId"))]
    return _verify_webtop(bios, uids, selected, devices, log)


def _distinct(values):
    out = []
    for v in values:
        if isinstance(v, str) and v not in out:
            out.append(v)
    return out


def _verify_webtop(bios, uids, selected, devices, log=print, max_tries=16):
    """Try the captured candidates with loginByBio; return the first credential that works."""
    combos = itertools.product(
        [b for b in _distinct(bios) if b], _distinct(uids) or [""], _distinct(selected) or [""], _distinct(devices) or [""], (True, False)
    )
    for n, (bio, uid, sel, dev, mobile) in enumerate(combos):
        if n >= max_tries:
            break
        cred = {"bio_login": bio, "unique_id": uid, "selected_user": sel, "device_id": dev, "is_mobile": mobile}
        client = webtop.Webtop(cred)
        try:
            client.login()
            students = client.students()
        except webtop.WebtopError as err:
            if err.code == "network":
                raise RuntimeError(f"cannot reach Webtop: {err}") from err
            time.sleep(1)
            continue
        log("Webtop login works. Students on this account: " + ", ".join(s["name"] for s in students))
        return cred, client.token
    raise RuntimeError("Webtop did not accept the captured login. Run setup-webtop again (log out first if already logged in).")


def capture_galim(timeout=600, log=print):
    sync_playwright = galim._sync_playwright()
    with sync_playwright() as p:
        browser = _browser(p)
        try:
            ctx = browser.new_context(
                locale="he-IL", timezone_id="Asia/Jerusalem", viewport={"width": 1366, "height": 850}, user_agent=galim.UA
            )
            page = ctx.new_page()
            page.goto(galim.LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            log(
                "A browser window is open on the Ministry of Education login (הזדהות אחידה).\n"
                "  Log in with the STUDENT's username and password - the same ones the child uses for Galim.\n"
                "  Use the username + password option (not SMS / ID card), so it can log in again by itself later.\n"
                "The window closes by itself once Galim Pro opens."
            )
            user = pwd = None
            deadline = time.time() + timeout
            while time.time() < deadline:
                if page.is_closed():
                    raise RuntimeError("the browser window was closed before the login finished")
                if "pro.galim.org.il" in page.url:
                    break
                try:
                    u, w = page.evaluate(
                        "() => [document.querySelector('#userName')?.value || '', document.querySelector('#password')?.value || '']"
                    )
                    if u and w:
                        user, pwd = u.strip(), w
                except Exception:
                    pass  # mid-navigation
                page.wait_for_timeout(400)
            else:
                raise RuntimeError("timed out waiting for the Galim login")
            header = None
            for _ in range(20):
                page.wait_for_timeout(700)
                header = galim.cookie_header(ctx.cookies())
                if header:
                    break
        finally:
            browser.close()
    if not header:
        raise RuntimeError("logged in, but Galim set no session cookie - try again")
    if not (user and pwd):
        raise RuntimeError(
            "logged in, but not with a username and password, so it could not be saved. "
            "Run setup-galim again and use the username + password option."
        )
    found = galim.tasks(header)
    log(f"Galim login works: {sum(not t['done'] for t in found)} open task(s), {sum(t['done'] for t in found)} submitted.")
    return {"username": user, "password": pwd}, header
