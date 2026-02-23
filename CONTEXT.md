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
- **Run the bot**: From a terminal outside Cursor, run `python3 telegram-bot/agent_bot.py`. The bot invokes `cursor agent` with `--print --trust --force` so it can run commands without prompting. Session ID is stored in `telegram-bot/.cursor_agent_session` so restarts keep the same conversation. The bot writes `telegram-bot/chat_id` when you message it (used by reminders). **Sending files**: Use `telegram-bot/attach_image.py /path/to/image.png` (images → `pending_images/`) or `telegram-bot/attach_file.py /path/to/file` (any file → `pending_attachments/`). The bot sends everything in those dirs with the next reply and then deletes them. No other attachment mode.
- **Systemd (optional)**: Units in `telegram-bot/systemd/`: copy to `~/.config/systemd/user/`, run `loginctl enable-linger $USER`, then `systemctl --user enable --now telegram-agent-bot.service`. For reminders: `systemctl --user enable --now telegram-reminders.timer`. Edit paths in the unit files if your clone is not in `~/projects/cursor-claw`.
- **Reminders**: `telegram-bot/reminders.json` holds `{"reminders": [{"at": "YYYY-MM-DDTHH:MM:SS", "text": "…", "prompt": "…"}]}` (local time for `at`). Use `"text"` for a fixed message at that time. Use `"prompt"` to run the Cursor agent at that time and send its reply to the user on Telegram. `run_reminders.py` runs every minute (via timer); due reminders are removed from the file immediately before processing so the same reminder is never run twice.

## Agent: web browsing and sending files

- **Web browsing**: Prefer **clawfox** ([github.com/jes/clawfox](https://github.com/jes/clawfox)) when you need to browse: `clawfox go <url>`, `clawfox show`, `clawfox screenshot`, etc. Screenshots are in `~/.clawfox/screenshots/`.
- **Sending images/files to the user on Telegram**: Run `telegram-bot/attach_image.py /path/to/image.png` (images) or `telegram-bot/attach_file.py /path/to/file` (any file). The bot sends everything in the pending dirs with your next reply and then deletes them. Use this e.g. after `clawfox screenshot` to send the user the screenshot.

## Projects / hosts

- (Add project names, hosts, and one-line purpose as they come up.)
