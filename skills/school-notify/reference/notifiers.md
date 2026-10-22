# Notification channels

`data/config.json` → `"notify"`: a list. Every notification goes to every
channel, and it counts as delivered if at least one channel accepted it.
Undelivered ones are queued and retried each round. After any change, run
`SN test-notify`.

A notification is `{"source": "webtop"|"galim"|..., "kind": "homework"|"message"|"lesson_event"|"galim_task"|"galim_grade"|"health"|"test", "title", "body", "url"}`.
Titles are Hebrew with an emoji (📚 homework, ✉️ message, 🌟/🚪/⚠️ lesson event, 📘 Galim, ⚠️/✅ health).

## ntfy (recommended)

Free phone push with no account. The topic name works as the password, so make it long and random.

1. Generate a topic yourself: `python3 -c "import secrets; print('school-' + secrets.token_urlsafe(12))"`.
2. She installs **ntfy** (Play Store / App Store), taps **+**, enters the topic, keeps the server `ntfy.sh`.
   - iPhone: "instant delivery" works out of the box with ntfy.sh.
   - Android: if pushes come late, tell her to turn off battery optimisation for ntfy in the app's settings.
3. Config:
   ```json
   {"type": "ntfy", "topic": "school-XXXXXXXXXXXXXXXX"}
   ```
   Optional `"server"` (a self-hosted ntfy) and `"token"` (an access token for a protected topic).
   Tapping the notification opens Webtop / Galim.

Both parents can subscribe to the same topic.

## Telegram

1. She opens Telegram, searches **@BotFather**, sends `/newbot`, picks any name and a username ending in `bot`. BotFather replies with a token like `123456:ABC…`. She sends you **only that token**. It controls only this new, empty bot.
   - For a family group instead: she creates the group, adds the bot, and sends any message in the group.
2. She opens her new bot and presses **Start** (or sends "hi").
3. `SN telegram-chat-id --token <token>` prints `chat_id<TAB>name`. A group's id is negative.
4. Config:
   ```json
   {"type": "telegram", "bot_token": "<token>", "chat_id": "<chat id>"}
   ```

## Email

Gmail: she needs 2-Step Verification on, then creates an app password at
https://myaccount.google.com/apppasswords. That gives 16 letters. Have her paste
them straight into `config.json` herself, or into a file you then read. Don't
take it through chat if she can avoid it.
```json
{"type": "email", "host": "smtp.gmail.com", "port": 587,
 "username": "her@gmail.com", "password": "<app password>", "to": ["her@gmail.com"]}
```
Port 465 uses SSL; any other port uses STARTTLS. Outlook: `smtp-mail.outlook.com` / 587.

## WhatsApp

WhatsApp has no free official API. Two practical routes, both through the `command` channel:

- **CallMeBot** (free, personal use, messages come from CallMeBot's number):
  she adds CallMeBot's number to her contacts and sends the activation sentence
  from https://www.callmebot.com/blog/free-api-whatsapp-messages/ (check the page
  for the current number and text). She gets an apikey back.
  ```json
  {"type": "command", "command": "curl -s -G 'https://api.callmebot.com/whatsapp.php' --data-urlencode \"phone=9725XXXXXXXX\" --data-urlencode \"apikey=XXXXXX\" --data-urlencode \"text=$SN_TITLE\n$SN_BODY\""}
  ```
- A paid gateway (Green API, Twilio WhatsApp): use its REST call in a `command` or `webhook` channel.

If she only wants WhatsApp because it's what she checks, suggest ntfy or Telegram
first: they are free, reliable, and messages come from a sender she controls.

## Pushover

A one-off purchase per platform, very reliable.
```json
{"type": "command", "command": "curl -s --form-string token=APP_TOKEN --form-string user=USER_KEY --form-string \"title=$SN_TITLE\" --form-string \"message=$SN_BODY\" --form-string \"url=$SN_URL\" https://api.pushover.net/1/messages.json"}
```

## Webhook / command (anything else)

```json
{"type": "webhook", "url": "https://…", "headers": {"Authorization": "Bearer …"}}
```
This POSTs the notification JSON. Works with Home Assistant webhooks, n8n, Zapier,
Make, and with Discord / Slack through a tiny relay. (Discord expects
`{"content": …}`, so use a `command` channel with curl instead.)

```json
{"type": "command", "command": "<shell command>"}
```
The command gets the notification JSON on stdin and `SN_TITLE`, `SN_BODY`,
`SN_URL`, `SN_KIND` in its environment. A non-zero exit counts as failed. On
Windows the command runs in `cmd.exe`, so use `%SN_TITLE%` there.
