# school-notify

Phone notifications from **Webtop (SmartSchool)** and **Galim Pro**, for parents
who don't run Home Assistant:

- 📚 new homework (and edits to it)
- ✉️ new messages from teachers and the school
- 🌟 🚪 ⚠️ lesson events: a good word, absences, remarks
- 📘 new Galim tasks with their due date, and new Galim grades

Pick where they go: ntfy, Telegram, email, WhatsApp (through CallMeBot), or any webhook / command.

## The easy way: let Claude do it

Open **Claude Code** (the terminal app, or the Code tab in the Claude desktop app) and say:

> Set up school notifications for me using https://github.com/igalav/school-notify

Claude installs everything, opens a browser window for you to log in (once for
Webtop, once with your child's Galim login), asks how you want to be notified,
tests it, and makes it start automatically. You don't need to know anything
technical.

If it ever stops (you'll get a "⚠️ אין עדכונים" message), say *"school notifications stopped"* to Claude.

Optional: install it as a Claude Code plugin, so the skill is always available:
```
/plugin marketplace add igalav/school-notify
/plugin install school-notify@school-notify
```

## בעברית, בקצרה

התראות לטלפון על שיעורי בית, הודעות ואירועי שיעור מוובטופ, ועל משימות וציונים
בגלים פרו, בלי Home Assistant. פותחים את Claude Code וכותבים:
**"תתקין לי התראות בית ספר מ-https://github.com/igalav/school-notify"**.
Claude יעשה את כל השאר. אתם רק מתחברים פעם אחת בחלון דפדפן שייפתח, ובוחרים לאן לשלוח את ההתראות.

## Privacy

Everything runs on your own computer. The logins are stored only in `data/config.json`
there (readable only by your user) and are sent only to Webtop and Galim
themselves. The notification text goes only to the channel you choose. Nothing
is sent to the author of this tool.

The Galim login is your **child's** Ministry of Education username and password.
It is stored because Galim sessions last only a few hours. If the password is
wrong, the tool stops trying, so it never locks the account.

## Without Claude

See [`skills/school-notify/SKILL.md`](skills/school-notify/SKILL.md). It is the
full procedure, written for Claude but readable by people:
```
git clone https://github.com/igalav/school-notify ~/school-notify && cd ~/school-notify
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium
.venv/bin/python -m school_notify setup-webtop
.venv/bin/python -m school_notify setup-galim
# add a channel to data/config.json ("notify": [...]), see skills/school-notify/reference/notifiers.md
.venv/bin/python -m school_notify test-notify
.venv/bin/python -m school_notify run
```

## Disclaimer

Unofficial, and not affiliated with SmartSchool, Galim or the Ministry of
Education. It makes the same requests the websites make in your browser, with
your own logins, every 30 minutes. If a site changes, it may stop working until
it is updated.
