# Keeping it running

`run` polls forever: one round, then sleep `poll_minutes`. It survives errors and
re-reads `config.json` each round. It prints one line per notification and per
error, so logs stay small. Paths below assume `~/school-notify`; replace `USER`
/ the home path with the real ones (the service needs absolute paths).

## macOS (launchd agent, starts at login)

`~/Library/LaunchAgents/il.school-notify.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>il.school-notify</string>
  <key>ProgramArguments</key><array>
    <string>/Users/USER/school-notify/.venv/bin/python</string>
    <string>-m</string><string>school_notify</string><string>run</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/USER/school-notify</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/USER/school-notify/data/log.txt</string>
  <key>StandardErrorPath</key><string>/Users/USER/school-notify/data/log.txt</string>
</dict></plist>
```
```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/il.school-notify.plist
launchctl kickstart -k gui/$(id -u)/il.school-notify     # restart (after git pull)
launchctl bootout gui/$(id -u)/il.school-notify          # stop / uninstall
```
- The install folder must **not** be under Documents / Desktop / Downloads / iCloud Drive. macOS privacy controls block launchd agents there (`Operation not permitted`).
- A sleeping laptop doesn't poll, and catches up when it wakes. For a desktop Mac that should stay awake: System Settings → Energy / Battery → "Prevent automatic sleeping when the display is off" (on power adapter).

## Linux (systemd user service)

`~/.config/systemd/user/school-notify.service`:
```ini
[Unit]
Description=School notifications (Webtop + Galim)
After=network-online.target

[Service]
WorkingDirectory=%h/school-notify
ExecStart=%h/school-notify/.venv/bin/python -m school_notify run
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
```
```
systemctl --user daemon-reload && systemctl --user enable --now school-notify
loginctl enable-linger $USER        # keep running when logged out / after reboot
journalctl --user -u school-notify -f
```
Playwright on Linux needs system libraries: `.venv/bin/playwright install --with-deps chromium` (needs sudo once).

## Windows (Task Scheduler, starts at logon)

In PowerShell:
```powershell
$py = "$HOME\school-notify\.venv\Scripts\pythonw.exe"
$a = New-ScheduledTaskAction -Execute $py -Argument "-m school_notify run" -WorkingDirectory "$HOME\school-notify"
$t = New-ScheduledTaskTrigger -AtLogOn
$s = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit 0 -StartWhenAvailable
Register-ScheduledTask -TaskName "school-notify" -Action $a -Trigger $t -Settings $s
Start-ScheduledTask -TaskName "school-notify"
```
`pythonw` has no console and no log, so check health with `SN status` (it lists errors and recent notifications).

## Docker (NAS, home server, Raspberry Pi 4/5 64-bit)

Do `setup-webtop` / `setup-galim` on a computer with a screen first, then copy
`data/config.json` and `data/state.json` to the server's `data/` folder (next to
`docker-compose.yml` in the repo).
`docker compose up -d --build`, logs with `docker compose logs -f`,
status with `docker compose exec school-notify python -m school_notify status`.

## Checking it works

After the first cycle: `SN status` shows `last poll` and `ok` per source. To see
that a real notification arrives without waiting for the school, run
`SN test-notify`.
