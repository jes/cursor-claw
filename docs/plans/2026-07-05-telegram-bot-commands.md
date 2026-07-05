# Telegram Bot Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Telegram slash commands (`/new`, `/summarize`, `/help`, `/status`) that control the Cursor agent session without requiring manual file edits.

**Architecture:** Extract command parsing and handlers into `telegram-bot/commands.py`. `agent_bot.py` intercepts command messages before the normal agent-forwarding path. Local commands mutate session state or reply immediately; agent-backed commands reuse `run_agent_streaming` with fixed prompts and optional `--mode ask`. `/new` uses `cursor agent create-chat` (returns a UUID) instead of deleting `.cursor_agent_session`.

**Tech Stack:** Python 3 stdlib (`unittest`), existing `agent_bot.py` subprocess/Telegram helpers, `cursor agent` CLI (`create-chat`, `--resume`, `--mode ask`).

**Author:** Auto  
**Date:** 2026-07-05

---

## Design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Session reset | `cursor agent create-chat` | Explicit ID before first message; no race on first `--resume` |
| `/summarize` | Agent prompt + `--mode ask --resume` | No native summarize CLI; ask mode is read-only and fits the use case |
| Command + text in one message | `/new fix the bug` → new session, then run `fix the bug` | Common Telegram pattern; avoids two round-trips |
| Mixed batch | Process commands first (in order), then agent-run remaining text | Preserves current batching for normal messages |
| Attachments + command | Attachments always go to agent; commands in same batch run first | e.g. `/new` then photo → new session, then agent gets photo prompt |
| Unknown `/foo` | Reply with help hint; do not forward to agent | Prevents accidental agent runs on typos |
| BotFather menu | `setMyCommands` on startup | Autocomplete in Telegram clients |

### v1 command set

| Command | Type | Behavior |
|---------|------|----------|
| `/new` | Local (+ optional agent) | `create-chat` → save session → reply "New session started." |
| `/new <text>` | Local + agent | Same, then run `<text>` on the new session |
| `/summarize` | Agent | Requires session; ask-mode prompt to summarize conversation so far |
| `/help` | Local | List commands and one-line descriptions |
| `/status` | Local | Session ID prefix (first 8 chars), whether session file exists |

### Out of scope (v1)

- `/cancel` mid-run (requires subprocess cancellation refactor)
- User-configurable commands via JSON
- Multi-user / per-chat session files (bot is single-user today)

---

## File structure

| File | Responsibility |
|------|----------------|
| `telegram-bot/commands.py` | Parse commands, registry, handler functions |
| `telegram-bot/agent_bot.py` | Batch loop calls command processor before agent |
| `telegram-bot/tests/test_commands.py` | Unit tests for parsing and routing |
| `README.md`, `CONTEXT.md` | User-facing command docs |

---

### Task 1: Command parsing module

**Files:**
- Create: `telegram-bot/commands.py`
- Create: `telegram-bot/tests/test_commands.py`

- [ ] **Step 1: Write failing tests for `parse_telegram_command`**

```python
# telegram-bot/tests/test_commands.py
import unittest
from commands import parse_telegram_command

class TestParseTelegramCommand(unittest.TestCase):
    def test_plain_command(self):
        self.assertEqual(parse_telegram_command("/new"), ("new", ""))

    def test_command_with_args(self):
        self.assertEqual(parse_telegram_command("/new fix the bug"), ("new", "fix the bug"))

    def test_bot_suffix_stripped(self):
        self.assertEqual(parse_telegram_command("/help@MyCursorBot"), ("help", ""))

    def test_not_a_command(self):
        self.assertIsNone(parse_telegram_command("hello"))
        self.assertIsNone(parse_telegram_command("/newbot"))  # BotFather, not ours

    def test_case_insensitive_name(self):
        self.assertEqual(parse_telegram_command("/NEW"), ("new", ""))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd telegram-bot && python3 -m unittest tests.test_commands -v`  
Expected: FAIL — `ModuleNotFoundError: commands`

- [ ] **Step 3: Implement parsing and constants**

```python
# telegram-bot/commands.py
"""Telegram slash commands for agent_bot."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

# Only match /word at start — not /newbot
_COMMAND_RE = re.compile(r"^/([a-zA-Z][a-zA-Z0-9_]*)((?:@[\w]+)?(?:\s+(.*))?|\s*)$", re.DOTALL)

SUMMARIZE_PROMPT = (
    "Summarize our conversation so far for the user. "
    "Use concise bullet points: main topics, decisions, open items, and any files touched. "
    "Do not start new work."
)


def parse_telegram_command(text: str) -> Optional[tuple[str, str]]:
    """Return (command_name_lower, args) or None if text is not a slash command."""
    text = (text or "").strip()
    m = _COMMAND_RE.match(text)
    if not m:
        return None
    name = m.group(1).lower()
    args = (m.group(3) or "").strip()
    return name, args


@dataclass
class CommandResult:
    """Outcome of handling one or more commands in a batch."""
    session_id: Optional[str]  # updated session, or None to leave unchanged
    agent_prompt: Optional[str]  # if set, run agent with this after commands
    handled: bool  # True if at least one command was recognized


KNOWN_COMMANDS = frozenset({"new", "summarize", "help", "status"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd telegram-bot && python3 -m unittest tests.test_commands -v`  
Expected: PASS (parsing tests only)

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/commands.py telegram-bot/tests/test_commands.py
git commit -m "feat(telegram): add slash command parsing module"
```

---

### Task 2: Local command handlers (`/new`, `/help`, `/status`)

**Files:**
- Modify: `telegram-bot/commands.py`
- Modify: `telegram-bot/tests/test_commands.py`

- [ ] **Step 1: Write failing tests for local handlers**

```python
# Add to telegram-bot/tests/test_commands.py
import os
import tempfile
from unittest.mock import patch, MagicMock
from commands import handle_commands, CommandResult

class TestHandleCommands(unittest.TestCase):
    def test_help_replies_without_agent(self):
        send = MagicMock()
        result = handle_commands(["/help"], session_id="abc", token="t", chat_id=1, send_message=send)
        self.assertTrue(result.handled)
        self.assertIsNone(result.agent_prompt)
        send.assert_called_once()
        self.assertIn("/new", send.call_args[0][2])

    def test_new_creates_session(self):
        send = MagicMock()
        with patch("commands.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="uuid-new-session\n", stderr="")
            with tempfile.TemporaryDirectory() as tmp:
                session_file = os.path.join(tmp, ".cursor_agent_session")
                result = handle_commands(
                    ["/new"], session_id=None, token="t", chat_id=1,
                    send_message=send, session_file=session_file, repo_root=tmp,
                )
        self.assertEqual(result.session_id, "uuid-new-session")
        self.assertTrue(os.path.isfile(session_file))
        with open(session_file) as f:
            self.assertEqual(f.read(), "uuid-new-session")

    def test_new_with_args_sets_agent_prompt(self):
        send = MagicMock()
        with patch("commands.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="uuid\n", stderr="")
            result = handle_commands(
                ["/new fix it"], session_id="old", token="t", chat_id=1,
                send_message=send, session_file=os.devnull, repo_root=".",
            )
        self.assertEqual(result.agent_prompt, "fix it")

    def test_status_shows_prefix(self):
        send = MagicMock()
        result = handle_commands(["/status"], session_id="abcdef12-rest", token="t", chat_id=1, send_message=send)
        self.assertTrue(result.handled)
        send.assert_called_once()
        self.assertIn("abcdef12", send.call_args[0][2])

    def test_summarize_requires_session(self):
        send = MagicMock()
        result = handle_commands(["/summarize"], session_id=None, token="t", chat_id=1, send_message=send)
        self.assertTrue(result.handled)
        self.assertIsNone(result.agent_prompt)
        self.assertIn("No active session", send.call_args[0][2])
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd telegram-bot && python3 -m unittest tests.test_commands -v`

- [ ] **Step 3: Implement `handle_commands` and helpers**

```python
# Add to telegram-bot/commands.py
import os
import subprocess
from typing import Any, Callable, List, Optional

HELP_TEXT = """Commands:
/new — start a fresh Cursor agent session
/new <prompt> — new session, then run <prompt>
/summarize — summarize the current conversation (read-only)
/status — show current session id
/help — this message"""


def create_chat_session(repo_root: str) -> str:
    out = subprocess.run(
        ["cursor", "agent", "create-chat"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "create-chat failed")
    session_id = out.stdout.strip()
    if not session_id:
        raise RuntimeError("create-chat returned empty id")
    return session_id


def handle_commands(
    batch_texts: List[str],
    *,
    session_id: Optional[str],
    token: str,
    chat_id: int,
    send_message: Callable[..., Any],
    session_file: str,
    repo_root: str,
) -> CommandResult:
    agent_prompt: Optional[str] = None
    handled = False
    sid = session_id

    for raw in batch_texts:
        parsed = parse_telegram_command(raw)
        if not parsed:
            if handled:
                continue  # skip non-commands after we've started command processing
            return CommandResult(session_id=sid, agent_prompt=None, handled=False)
        name, args = parsed
        if name not in KNOWN_COMMANDS:
            send_message(token, chat_id, f"Unknown command /{name}. Send /help.", use_rich=False)
            handled = True
            continue

        handled = True
        if name == "help":
            send_message(token, chat_id, HELP_TEXT, use_rich=False)
        elif name == "status":
            if sid:
                send_message(token, chat_id, f"Session: {sid[:8]}…", use_rich=False)
            else:
                send_message(token, chat_id, "No active session. Send /new to start.", use_rich=False)
        elif name == "new":
            try:
                sid = create_chat_session(repo_root)
                with open(session_file, "w") as f:
                    f.write(sid)
                send_message(token, chat_id, "New session started.", use_rich=False)
                if args:
                    agent_prompt = args
            except Exception as e:
                send_message(token, chat_id, f"Could not create session: {e}", use_rich=False)
        elif name == "summarize":
            if not sid:
                send_message(token, chat_id, "No active session. Send /new first.", use_rich=False)
            else:
                agent_prompt = SUMMARIZE_PROMPT

    return CommandResult(session_id=sid, agent_prompt=agent_prompt, handled=handled)
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/commands.py telegram-bot/tests/test_commands.py
git commit -m "feat(telegram): implement /new /help /status command handlers"
```

---

### Task 3: Integrate commands into `agent_bot.py`

**Files:**
- Modify: `telegram-bot/agent_bot.py` (main loop ~593–618)
- Modify: `telegram-bot/agent_bot.py` (`run_agent_streaming` — add optional `mode`)

- [ ] **Step 1: Add `agent_mode` parameter to `run_agent_streaming`**

```python
# In run_agent_streaming signature, add:
def run_agent_streaming(
    prompt: str,
    resume_session: Optional[str],
    token: str,
    chat_id: int,
    *,
    agent_mode: Optional[str] = None,  # "ask" | "plan" | None
) -> Optional[str]:
    # ...
    cmd = [
        "cursor", "agent", "--print", "--trust", "--force",
        "--workspace", REPO_ROOT,
        "--model", "Auto",
        "--output-format", "stream-json",
    ]
    if agent_mode:
        cmd.extend(["--mode", agent_mode])
    if resume_session:
        cmd.extend(["--resume", resume_session])
    cmd.append(prompt)
```

- [ ] **Step 2: Wire command handling in main loop**

Replace the block from `save_chat_id(chat_id)` through `save_session(session_id)` with:

```python
        save_chat_id(chat_id)

        from commands import handle_commands, parse_telegram_command

        # If every text line is a command, handle via command path only
        command_texts = [t for t in batch_texts if parse_telegram_command(t)]
        non_command_texts = [t for t in batch_texts if not parse_telegram_command(t)]

        if command_texts:
            result = handle_commands(
                command_texts,
                session_id=session_id,
                token=token,
                chat_id=chat_id,
                send_message=send_message,
                session_file=SESSION_FILE,
                repo_root=REPO_ROOT,
            )
            if result.session_id is not None:
                session_id = result.session_id
                save_session(session_id)
            agent_prompt = result.agent_prompt
            if non_command_texts:
                extra = "\n\n".join(non_command_texts)
                agent_prompt = f"{agent_prompt}\n\n{extra}" if agent_prompt else extra
            elif not agent_prompt and not batch_image_paths and not batch_document_paths:
                continue
            text = agent_prompt or ""
        else:
            text = "\n\n".join(batch_texts) if batch_texts else ""

        # Append attachment hints (unchanged)
        if batch_image_paths:
            text += "\n\n[User sent %d image(s)...]" % (len(batch_image_paths), ", ".join(batch_image_paths))
        # ... documents idem ...

        if not text.strip():
            continue

        summarize_mode = "ask" if command_texts and any(
            parse_telegram_command(t) and parse_telegram_command(t)[0] == "summarize" for t in command_texts
        ) else None

        send_chat_action(token, chat_id, "typing")
        session_id = run_agent_streaming(
            text, session_id, token, chat_id, agent_mode=summarize_mode
        )
        save_session(session_id)
```

- [ ] **Step 3: Register BotFather commands on startup**

```python
def register_bot_commands(token: str) -> None:
    commands = [
        {"command": "new", "description": "Start a new agent session"},
        {"command": "summarize", "description": "Summarize current conversation"},
        {"command": "status", "description": "Show session id"},
        {"command": "help", "description": "List commands"},
    ]
    try:
        api(token, "setMyCommands", commands=commands)
    except Exception as e:
        print("setMyCommands failed: %s" % e, file=sys.stderr)

# Call once in main() after load_config()
```

- [ ] **Step 4: Manual smoke test**

1. Start bot: `python3 telegram-bot/agent_bot.py`
2. Send `/help` → plain-text command list, no agent run
3. Send `/new` → "New session started."
4. Chat normally → session persists across bot restart
5. Send `/summarize` → ask-mode summary of conversation
6. Send `/new deploy the feature` → new session + agent runs "deploy the feature"
7. Send `/unknown` → error hint, not forwarded to agent

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/agent_bot.py
git commit -m "feat(telegram): wire slash commands into agent bot loop"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md` (section after step 5)
- Modify: `CONTEXT.md` (Telegram bot section)

- [ ] **Step 1: Add README subsection "Bot commands"**

Document `/new`, `/new <prompt>`, `/summarize`, `/status`, `/help` with one line each. Note that `/summarize` uses ask mode and does not edit files.

- [ ] **Step 2: Update CONTEXT.md**

Add bullet under Telegram bot: commands available; session still in `.cursor_agent_session`; `/new` uses `create-chat`.

- [ ] **Step 3: Commit**

```bash
git add README.md CONTEXT.md
git commit -m "docs: document Telegram bot slash commands"
```

---

## Test plan (manual)

| Step | Action | Expected |
|------|--------|----------|
| 1 | `/help` | Command list, no typing/agent delay beyond instant reply |
| 2 | `/new` | Confirmation; `.cursor_agent_session` updated |
| 3 | "what repo is this?" | Agent answers with workspace context |
| 4 | `/summarize` | Bullet summary referencing step 3 |
| 5 | Restart bot, send "continue" | Same session (context retained) |
| 6 | `/new` then immediate follow-up messages batched | Commands processed before agent text |
| 7 | Photo + `/new` in same batch | New session, then agent sees photo paths |

---

## Future extensions (not in this plan)

- `/cancel` — kill in-flight `subprocess.Popen` from `run_agent_streaming`
- `/model <name>` — override `--model` for one shot
- `/plan <task>` — `--mode plan` for read-only planning
- Per-command timeout overrides in `config`

---

## Execution handoff

**Plan saved to `docs/plans/2026-07-05-telegram-bot-commands.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement all tasks in this session with checkpoints

Which approach?
