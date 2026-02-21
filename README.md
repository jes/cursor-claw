# Cursor-Claw: Telegram ↔ Cursor Agent

Use a Telegram bot to talk to the [Cursor](https://cursor.com) agent from your phone or anywhere. Messages you send to the bot are forwarded to `cursor agent`; the agent’s reply is sent back to you in Telegram.

**Requirements:**

- Python 3
- [Cursor](https://cursor.com) with the CLI installed (`cursor` on your PATH)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

---

## Setup

### 1. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts (name and username).
3. Copy the **token** BotFather gives you (e.g. `123456789:ABCdefGHI...`). Keep it secret; don’t commit it.

### 2. Get your Telegram user ID

From this repo’s root:

```bash
TELEGRAM_BOT_TOKEN='your_token_here' python3 telegram-bot/echo_user_ids.py
```

Send any message to your new bot. The script will print your `user_id` (a number). Note it; you’ll need it in the next step. Stop the script with Ctrl+C.

### 3. Configure the agent bot

```bash
cp telegram-bot/config.example telegram-bot/config
```

Edit `telegram-bot/config` and set:

- `TELEGRAM_BOT_TOKEN` — the token from BotFather
- `TELEGRAM_ALLOWED_USER_ID` — the user ID from step 2 (only this user can use the bot)

**Do not commit `telegram-bot/config`.** It’s listed in `.gitignore`.

### 4. Run the bot

Open a terminal **outside** Cursor (so the agent can run in the background). From the **clone root** of this repo:

```bash
python3 telegram-bot/agent_bot.py
```

Leave it running. When you send a text message to your bot on Telegram, it will run `cursor agent` in this workspace and reply with the agent’s output.

---

## How it works

- The bot only accepts messages from the user ID in `config`; others are ignored.
- It runs `cursor agent --print --trust --force --workspace <repo_root> ...` so the agent can execute commands without interactive prompts.
- The agent session is persisted in `telegram-bot/.cursor_agent_session`, so restarts of the bot keep one continuous conversation.
- Run the bot from the repo root so `--workspace` points at your clone; open that same folder in Cursor when you want to work there.

---

## Security

- **Never commit** `telegram-bot/config` or any file containing your bot token or user ID.
- Only the configured user ID can use the bot; everyone else is dropped.
- The agent runs with `--trust --force`, so it can run commands and edit files without asking. Use only with a bot that only you can message.

---

## License

Use and modify as you like. No warranty.
