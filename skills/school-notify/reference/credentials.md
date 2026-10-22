# How the logins work, and manual fallbacks

## Webtop (SmartSchool)

- API: `https://webtopserver.smartschool.co.il/server/api/<path>`. Every call is
  a POST with JSON, the `{status, data}` envelope, and a single cookie `webToken`.
- Password login (`LoginByUserNameAndPassword`) needs a reCAPTCHA, so it can't run unattended.
- **Remember me** (זכור אותי) registers a credential that lasts about a year.
  `user/loginByBio` turns it into a fresh `webToken` with no password and no captcha:
  ```json
  {"id": "<bio_login>", "param1": "2", "param2": "<device_id, usually empty>",
   "param3": "<selected_user>", "param4": "<unique_id>", "param5": "true"}
  ```
  The checkbox appears **only in Webtop's mobile layout**, so setup opens
  `https://webtop.smartschool.co.il/account/login?device=1`, which forces it on a desktop.
- The tool keeps the `webToken` it got in `state.json` and calls `loginByBio`
  again only when a call answers HTTP 401 or `status: false`. (A stale session
  also shows up as `status: false` on `dashboard/InitDashboard`.)
- Calls used: `dashboard/InitDashboard` (students, field `childrens`),
  `PupilCard/GetPupilLessonsAndHomework` (moduleID 11, weekIndex 0 / -1),
  `PupilCard/GetPupilDiciplineEvents` (moduleID 4, the whole year),
  `messageBox/GetMessagesInbox` (page 1), and `messageBox/GetMessagesInboxData`
  (a message body, which **marks it read**). The misspellings are the server's.
- A parent account with several children: all of them are polled, and each title is prefixed with the child's first name.

### Manual fallback (if the setup window can't be used)

On any computer with Chrome:
1. Log out of Webtop. Open `https://webtop.smartschool.co.il/account/login?device=1`.
2. Log in with **זכור אותי** ticked.
3. DevTools (F12) → Application → Local storage → `https://webtop.smartschool.co.il`. Copy:
   - `SavedUser` → `bio_login` (long, ~500 chars). It is the same value as the `id` in the `writeBio` request on the Network tab.
   - `wt_uid` → `unique_id`
   - `selectedUser` → `selected_user`
4. Put them in a file *she* creates (not the chat):
   `{"bio_login": "...", "unique_id": "...", "selected_user": "..."}`,
   then run `SN import-webtop < that-file` and delete the file.
   It verifies the values and saves them.
5. In DevTools, run `localStorage.removeItem('openedFromDevice')` to get the desktop layout back.

`loginByBio` never appears in the desktop layout. Only the mobile layout registers the credential.

## Galim Pro

- Tasks: `POST https://lms.galim.org.il/personal_api/tasks`, with the session
  cookies `SID`, `LMSAffinity` and `LMSAffinityCORS`, plus `Origin: https://pro.galim.org.il`.
  The body must contain **every** `filterData` field the web app sends, or the
  server answers 500 (see `school_notify/galim.py`). `completedActive: false`
  means open tasks and `true` means submitted ones. A dead session gives
  401/403, HTML, or empty `userdata`.
- The session lasts ~8 h. Login starts at `https://userdata.galim.org.il/login_idm`,
  which goes to the Ministry SSO `lgn.edu.gov.il` (an F5 bot check, Angular form
  `#userName` / `#password`, where the password field is read-only until
  clicked). On success it lands on `pro.galim.org.il`. The tool does this in
  headless Chromium (`galim.login`) with a normal desktop Chrome user agent.
- Account protection, in `galim.guarded_login`: at most one login per 10 min,
  back-off 10 min → 30 min → 1 h → 3 h, and a **full stop** on the ministry's
  wrong-password / locked / expired messages until the saved credentials change
  (`setup-galim`). Keep these.
- `setup-galim` reads the username and password from the form fields while she
  types, in a visible browser, and keeps them only if the login succeeds.
- No visible browser possible (a headless server): set the env vars
  `GALIM_USERNAME` / `GALIM_PASSWORD` for the service (they override
  `config.json`), or have her type them into `data/config.json` herself as
  `"galim": {"username": "...", "password": "..."}`. Then run `SN galim-login-test`.
- If the headless login fails with `bot_check` / `unexpected_page` but the
  headed setup works, the ministry is detecting headless mode. Run the service
  on a machine with a desktop session, or under Xvfb on Linux and patch
  `galim.login` to `headless=False`.
