# Context (living memory for this workspace)

**Instructions for the assistant (read every session):**

Chat context is lost each session. This file is the only persistent memory for this workspace. It must contain (1) important context about the user's environment and (2) the instructions that ensure it *keeps* being updated.

- **Read this file** when working here (start of session or when you need context).
- **Update this file** when you learn something important and durable: new host, project, account, path, convention, preference. Add or amend; keep entries concise.
- **Prune** when something is outdated or irrelevant. Delete rather than leave stale.
- **Store only durable facts.** Do not store ephemeral or easily re-discovered data (e.g. disk space—use `df`, `du`, etc. when needed).
- **Commit** when you change this file. Use clear messages, e.g. `context: add host X`, `context: remove project Y`.

---

## Workspace

- **cursor-claw**: Workspace with Telegram–Cursor agent integration. The bot in `telegram-bot/` forwards messages from Telegram to the Cursor agent and replies with the agent's output.

## Telegram bot

- **Location**: `telegram-bot/`
- **Config**: Copy `telegram-bot/config.example` to `telegram-bot/config` and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_ID`. Do not commit `config` (it is in `.gitignore`).
- **Discover your user ID**: Run `TELEGRAM_BOT_TOKEN=<token> python3 telegram-bot/echo_user_ids.py`, then send a message to your bot; the script prints your user ID.
- **Run the bot**: From a terminal outside Cursor, run `python3 telegram-bot/agent_bot.py`. The bot invokes `cursor agent` with `--print --trust --force` so it can run commands without prompting. Session ID is stored in `telegram-bot/.cursor_agent_session` so restarts keep the same conversation.

## Projects / hosts

- (Add project names, hosts, and one-line purpose as they come up.)
