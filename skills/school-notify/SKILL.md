---
name: school-notify
description: Set up, run, change or fix push notifications for the Israeli school portals Webtop (SmartSchool, סמארט סקול / וובטופ) and Galim Pro (גלים פרו), without Home Assistant. Covers new homework, teacher and school messages, lesson events (praise, absences, remarks), new Galim tasks and Galim grades. Use when a parent wants school notifications on their phone, when such notifications stopped arriving, or when they want to change what is sent or where.
---

# School notifications (Webtop + Galim Pro)

You are setting this up **for a parent who should not need to learn anything**.
Do every technical step yourself: cloning, installing, editing config, testing,
making it start automatically. The parent does only three things: log in
in a browser window that you open, choose how she wants to be notified, and
install an app on her phone if the channel she picks needs one. Talk to her in
the language she writes in (usually Hebrew), with no jargon. Ask one short
question at a time, and only when you can't decide it yourself.

## What the tool is

A Python process (`python -m school_notify run`) that polls every 30 min:

| Source | What it notices | Login it needs |
|---|---|---|
| Webtop | new homework (an edited homework text counts as new), new inbox messages, new lesson events (🌟 praise, 🚪 absence, ⚠️ remarks) | the **parent's** Webtop account, once, with "זכור אותי" (remember me). It stays valid for ~1 year |
| Galim Pro | new open tasks (with due date), new grades | the **student's** Ministry of Education username + password (הזדהות אחידה), the same ones the child uses for Galim. It is saved, because Galim sessions last ~8 h and the tool logs in again by itself |

The first successful round only *records* what already exists, so setup
doesn't flood the phone. Webtop needs only the Python standard library. Galim,
and the one-time browser logins, need Playwright + Chromium.

All files live in `<install>/data/`: `config.json` (credentials and choices,
mode 600) and `state.json` (what was seen, sessions, health).

## Procedure

### 1. Install

- Pick an always-on machine if she has one (desktop, home server, Raspberry Pi,
  NAS). Otherwise her laptop is fine: nothing is lost while it sleeps, items
  just arrive when it wakes. The **browser logins in steps 3–4 need a machine
  with a screen**. For a headless server, do steps 3–4 on her laptop and copy
  `data/config.json` + `data/state.json` over (see `reference/running.md`).
- Clone into a plain folder in her home directory. **Not** in Documents,
  Desktop or iCloud: macOS blocks background services from those folders.
  ```
  git clone https://github.com/igalav/school-notify ~/school-notify
  cd ~/school-notify
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/playwright install chromium      # Linux: add --with-deps (needs sudo)
  ```
  You need Python ≥ 3.9 (Windows: `py -m venv .venv`, then `.venv\Scripts\python`).
  If this skill came from an installed plugin, the repo is also at
  `${CLAUDE_PLUGIN_ROOT}`, but still clone it as above: the plugin cache moves
  on updates and the service needs a stable path.
- Below, `SN` means `~/school-notify/.venv/bin/python -m school_notify`, run
  from `~/school-notify`.

### 2. Ask what she wants

Ask together (AskUserQuestion works well):
- Which sources: Webtop, Galim, or both. Does the child even use Galim?
- How she wants to get them. Show the options in step 5 with one line each.

### 3. Webtop login (if wanted)

Tell her first, in her language: *"A browser window will open on the Webtop
login. Log in with your parent username and password, and **tick 'זכור אותי'
before you press login**. If there is an 'I'm not a robot' box, solve it. The
window closes by itself."* Then run, with a Bash timeout of 600000 ms:
```
SN setup-webtop
```
It captures the remember-me credential, checks it against Webtop and prints the
student names. Confirm the names with her. Failures:
- *"did not register a remember-me login"*: she didn't tick זכור אותי. Run it again.
- *"did not accept the captured login"*: run it again. If it keeps failing, use
  the manual path in `reference/credentials.md`.
- She logs in to Webtop through the ministry (הזדהות אחידה) instead of a Webtop
  password: that works too, as long as she ticks זכור אותי on the Webtop page.

### 4. Galim login (if wanted)

Tell her: *"A window will open on the Ministry of Education login. Log in as
**your child**, with the child's username and password. Use the username +
password option, not an SMS code. It's saved on this computer only, so it can
log in again by itself every few hours."* Then:
```
SN setup-galim            # Bash timeout 600000
SN galim-login-test       # proves the unattended (headless) login works on this machine
```
If she doesn't know the child's password, the child does (they use it at
school). Otherwise the homeroom teacher or the school's ICT coordinator can
reset it. **Never ask her to type a password into the chat.** The browser
window is the only place it goes.

### 5. Notification channel

Offer these and let her pick. More than one is fine, e.g. both parents.
Full setup steps and config snippets are in `reference/notifiers.md`.

| Channel | Good for | Her effort |
|---|---|---|
| **ntfy** (recommended) | real phone push, free, no account | install the ntfy app, subscribe to a topic you give her |
| **Telegram** | if she already lives in Telegram; can go to a family group | create a bot with @BotFather (you guide), press Start |
| **Email** | no app at all | a Gmail app password (needs 2-step verification) |
| **WhatsApp** | no official free API; possible through CallMeBot (free, personal) or a paid gateway | a one-time activation message |
| **anything else** (Pushover, Slack, Discord, her own Home Assistant…) | `webhook` or `command` channel | depends |

Write the choice into `data/config.json` under `"notify"` (a list), then run
`SN test-notify` and ask her whether it arrived.

### 6. Options

Defaults are sensible; mention them in one message and change only what she asks for:
- `quiet_hours`: e.g. `"22:00-07:00"`. Notifications wait and arrive when it ends. Default: none.
- `webtop.message_bodies`: include the full message text. **Reading the text marks the message as read on Webtop.** Default: off (subject only).
- `webtop.attendance`: absence/lateness events. Default: on.
- `webtop.homework`, `webtop.messages`, `webtop.lesson_events`, `galim.new_tasks`, `galim.grades`: all on.
- `poll_minutes`: 30. Don't go below 15 (minimum 10): be gentle with the school's servers.
- `alert_after_hours`: 12. After a source has failed this long she gets one "⚠️ אין עדכונים" push. A rejected login alerts at once.

They go in `config.json` as `"options": {"quiet_hours": "22:00-07:00", "webtop": {"message_bodies": true}}`.
Only the keys being changed are needed.

### 7. First round and preview

```
SN poll --preview     # shows what current items look like as notifications; sends and saves nothing
SN poll               # real first round: records everything silently
SN status
```
Show her two or three preview lines so she knows what to expect.

### 8. Keep it running

Make it start automatically and restart if it dies. Follow `reference/running.md`
for her OS (macOS launchd agent, Linux systemd user service, Windows Task
Scheduler, or Docker). Then check `SN status` after one cycle.

### 9. Wrap up

Tell her briefly what she'll get, and the one thing to remember: *if a
"⚠️ אין עדכונים מ..." message ever arrives, open Claude and say "school
notifications stopped". Re-running the login fixes it.* Expect it when the
child changes the Galim password, and about once a year for Webtop.

## Fixing / changing an existing setup

Start with `SN status` (and the service log, see `reference/running.md`).

| `status` code | Meaning | Fix |
|---|---|---|
| `credential_rejected` (webtop) | the remember-me login expired or was revoked (e.g. she logged out of all devices) | step 3 again |
| `bad_credentials` (galim) | wrong / changed / expired child password, or account locked. **Logins are stopped** until setup is re-run | step 4 again. If locked, wait for the school to unlock it |
| `waiting` (galim) | a login was postponed by the pacing rules (≤ 1 per 10 min, back-off 10 min → 3 h) | nothing, it retries by itself |
| `bot_check`, `unexpected_page`, `timeout` (galim) | the ministry login page changed or showed a captcha / SMS step | try `SN galim-login-test`. If it persists, run `setup-galim` (headed) to look, and see `reference/credentials.md` |
| `network`, `webtop_down`, `galim_down` | the machine is offline or the site is down | usually passes. Check the internet |
| `no_playwright` | Playwright / Chromium missing in the venv the service uses | redo the install in step 1 |

To change channels or options, edit `data/config.json` and run `SN test-notify`.
The running service reads the file again every round, so it needs no restart.
To update: `git pull` in `~/school-notify`, then restart the service.

## Rules

- Never print, cat or paste `data/config.json` or `state.json` into the chat. They hold passwords and session tokens. Use `SN status`.
- Never commit `data/` anywhere (it is git-ignored). Never send the credentials to any service other than Webtop / Galim themselves.
- Don't loosen the Galim pacing and don't loop `setup-galim` / `galim-login-test`: repeated failed ministry logins lock the child's account.
- `poll` and the service share a lock, so running `SN poll` by hand while the service runs is safe.
- This is unofficial: it makes the same requests the websites make. If a site changes, the errors in `status` say where. `reference/credentials.md` explains how each login works, to help fix it.
