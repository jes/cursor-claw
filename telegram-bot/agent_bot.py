#!/usr/bin/env python3
"""
Telegram bot: only accepts messages from the allowed user (see config); forwards
them to Cursor agent and sends the agent's response back. Uses --output-format json
and --resume to keep one conversation session across restarts (session_id stored in
.cursor_agent_session). All other users are dropped.

Supports text and photos: photos are downloaded to telegram-bot/received_images/
and their workspace-relative paths are added to the prompt so the agent can read them.

Config: create telegram-bot/config from config.example with TELEGRAM_BOT_TOKEN and
TELEGRAM_ALLOWED_USER_ID. Run from a terminal outside Cursor.
"""

import os
import sys
import time
import json
import subprocess
import threading
import urllib.request
import urllib.error
from typing import Optional, Tuple

TYPING_INTERVAL = 4  # Telegram typing indicator lasts ~5s; re-send before it expires
DEFAULT_AGENT_TIMEOUT = 0  # 0 = unlimited; set CURSOR_AGENT_TIMEOUT in config or env to limit

BASE = "https://api.telegram.org/bot"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config")
SESSION_FILE = os.path.join(SCRIPT_DIR, ".cursor_agent_session")
CHAT_ID_FILE = os.path.join(SCRIPT_DIR, "chat_id")
OFFSET_FILE = os.path.join(SCRIPT_DIR, ".telegram_offset")
RECEIVED_IMAGES_DIR = os.path.join(SCRIPT_DIR, "received_images")


def get_agent_timeout() -> int:
    """Agent subprocess timeout in seconds. Config file or env CURSOR_AGENT_TIMEOUT, else default."""
    timeout = None
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k == "CURSOR_AGENT_TIMEOUT" and v:
                        try:
                            timeout = int(v)
                        except ValueError:
                            pass
                        break
    if timeout is None:
        try:
            timeout = int(os.environ.get("CURSOR_AGENT_TIMEOUT", str(DEFAULT_AGENT_TIMEOUT)))
        except ValueError:
            timeout = DEFAULT_AGENT_TIMEOUT
    return timeout if timeout > 0 else 0  # 0 = unlimited


def load_config() -> Tuple[str, int]:
    """Load TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID from config file or env."""
    token = None
    user_id = None
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k == "TELEGRAM_BOT_TOKEN" and v:
                        token = v
                    elif k == "TELEGRAM_ALLOWED_USER_ID" and v:
                        try:
                            user_id = int(v)
                        except ValueError:
                            pass
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in %s or env." % CONFIG_FILE, file=sys.stderr)
        sys.exit(1)
    if user_id is None:
        uid_env = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
        if uid_env:
            try:
                user_id = int(uid_env)
            except ValueError:
                pass
        if user_id is None:
            print("Set TELEGRAM_ALLOWED_USER_ID in %s or env." % CONFIG_FILE, file=sys.stderr)
            sys.exit(1)
    return token, user_id


def api(token, method, **params):
    url = f"{BASE}{token}/{method}"
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def send_chat_action(token, chat_id, action="typing"):
    try:
        api(token, "sendChatAction", chat_id=chat_id, action=action)
    except Exception:
        pass


def send_message(token, chat_id, text, parse_mode="Markdown"):
    chunk = 4096
    for i in range(0, len(text), chunk):
        part = text[i : i + chunk]
        try:
            api(token, "sendMessage", chat_id=chat_id, text=part, parse_mode=parse_mode)
        except urllib.error.HTTPError as e:
            if e.code == 400 and parse_mode:
                api(token, "sendMessage", chat_id=chat_id, text=part)
            else:
                raise


def load_session() -> Optional[str]:
    if os.path.isfile(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                return f.read().strip() or None
        except Exception:
            pass
    return None


def save_session(session_id: Optional[str]) -> None:
    if session_id:
        try:
            with open(SESSION_FILE, "w") as f:
                f.write(session_id)
        except Exception as e:
            print("Could not save session: %s" % e, file=sys.stderr)


def save_chat_id(chat_id: int) -> None:
    """Persist chat_id so run_reminders.py can send scheduled messages to the user."""
    try:
        with open(CHAT_ID_FILE, "w") as f:
            f.write(str(chat_id))
    except Exception as e:
        print("Could not save chat_id: %s" % e, file=sys.stderr)


def download_telegram_photo(token: str, file_id: str, dest_path: str) -> bool:
    """Download a Telegram file by file_id to dest_path. Returns True on success."""
    try:
        out = api(token, "getFile", file_id=file_id)
        if not out.get("ok"):
            return False
        file_path = (out.get("result") or {}).get("file_path")
        if not file_path:
            return False
        # getFile returns file_path like "photos/file_0.jpg"; download at:
        url = "https://api.telegram.org/file/bot%s/%s" % (token, file_path)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print("Download photo failed: %s" % e, file=sys.stderr)
        return False


def load_offset() -> int:
    """Load last getUpdates offset so restarts don't re-process the same message."""
    if os.path.isfile(OFFSET_FILE):
        try:
            with open(OFFSET_FILE) as f:
                return int(f.read().strip())
        except (ValueError, OSError):
            pass
    return 0


def save_offset(offset: int) -> None:
    """Persist getUpdates offset so a crash during agent run doesn't cause re-processing."""
    try:
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except Exception as e:
        print("Could not save offset: %s" % e, file=sys.stderr)


def run_agent(prompt: str, resume_session: Optional[str]) -> Tuple[str, Optional[str]]:
    """Run cursor agent directly; persist session_id so restarts keep context."""
    if not prompt.strip():
        return "(no prompt)", resume_session
    cmd = [
        "cursor", "agent", "--print", "--trust", "--force",
        "--workspace", REPO_ROOT,
        "--model", "Auto",
        "--output-format", "json",
    ]
    if resume_session:
        cmd.extend(["--resume", resume_session])
    cmd.append(prompt)
    timeout_sec = get_agent_timeout()
    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_sec or None,  # 0 = unlimited
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()

        session_id = resume_session
        response_text = None
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = obj.get("session_id") or obj.get("sessionId") or obj.get("chatId")
            if sid:
                session_id = str(sid)
            if "result" in obj and isinstance(obj["result"], str):
                response_text = obj["result"].strip()
            elif response_text is None:
                for key in ("text", "content", "response", "message", "output"):
                    if key in obj and isinstance(obj[key], str):
                        response_text = obj[key]
                        break

        if response_text is None and out:
            try:
                obj = json.loads(out)
                session_id = obj.get("session_id") or obj.get("sessionId") or session_id
                response_text = obj.get("result") or obj.get("text") or obj.get("content") or out
                if isinstance(response_text, dict):
                    response_text = response_text.get("content", str(response_text))
            except json.JSONDecodeError:
                response_text = out

        if result.returncode != 0 and not response_text:
            response_text = err or "Agent exited with code %s" % result.returncode
        return response_text or "(no output)", session_id
    except subprocess.TimeoutExpired:
        return "Agent timed out after %s seconds." % timeout_sec, resume_session
    except Exception as e:
        return "Error running agent: %s" % e, resume_session


def main():
    token, allowed_user_id = load_config()
    offset = load_offset()
    if offset:
        print("Resuming from update offset %s." % offset, file=sys.stderr)
    session_id = load_session()
    if session_id:
        print("Resuming session: %s..." % session_id[:20], file=sys.stderr)
    print("Agent bot running. Only user_id=%s accepted; others dropped." % allowed_user_id, file=sys.stderr)
    print("Ctrl+C to stop.", file=sys.stderr)
    while True:
        try:
            out = api(token, "getUpdates", offset=offset, timeout=30)
        except urllib.error.URLError as e:
            print("API error: %s" % e, file=sys.stderr)
            time.sleep(5)
            continue
        if not out.get("ok"):
            print("API not ok: %s" % out, file=sys.stderr)
            time.sleep(5)
            continue
        updates = out.get("result", [])
        if not updates:
            continue
        # Collect all new messages from allowed user (batch: e.g. 3 messages sent while idle)
        batch_texts = []
        batch_image_paths = []  # workspace-relative paths for agent
        chat_id = None
        for i, upd in enumerate(updates):
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            uid = (msg.get("from") or {}).get("id")
            if uid != allowed_user_id:
                continue
            if chat_id is None:
                chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            if text:
                batch_texts.append(text)
            # Photos: download largest size and pass path to agent so it can read the image
            photos = msg.get("photo") or []
            if photos:
                file_id = photos[-1].get("file_id")  # largest size
                if file_id:
                    os.makedirs(RECEIVED_IMAGES_DIR, exist_ok=True)
                    local_name = "photo_%s_%s.jpg" % (upd["update_id"], i)
                    dest_path = os.path.join(RECEIVED_IMAGES_DIR, local_name)
                    if download_telegram_photo(token, file_id, dest_path):
                        batch_image_paths.append(os.path.join("telegram-bot", "received_images", local_name))
                caption = (msg.get("caption") or "").strip()
                if caption:
                    batch_texts.append(caption)
        # Advance offset past entire batch so we don't re-process
        offset = updates[-1]["update_id"] + 1
        save_offset(offset)
        if not batch_texts and not batch_image_paths:
            continue
        if chat_id is None:
            continue
        save_chat_id(chat_id)
        # Concatenate all new messages into one prompt (e.g. 3 messages -> one agent run)
        text = "\n\n".join(batch_texts) if batch_texts else ""
        if batch_image_paths:
            text += "\n\n[User sent %d image(s). They are in the workspace at: %s. Look at them and respond accordingly.]" % (
                len(batch_image_paths),
                ", ".join(batch_image_paths),
            )
        if not text.strip():
            continue
        if len(batch_texts) > 1:
            print("Running agent for %d messages as one prompt (%s...)..." % (len(batch_texts), text[:50]), file=sys.stderr)
        else:
            print("Running agent for prompt: %s..." % text[:60], file=sys.stderr)
        send_chat_action(token, chat_id, "typing")
        result = [None, None]  # [response_text, session_id]
        done = threading.Event()

        def run():
            result[0], result[1] = run_agent(text, session_id)
            done.set()

        t = threading.Thread(target=run)
        t.start()
        while not done.wait(TYPING_INTERVAL):
            send_chat_action(token, chat_id, "typing")
        response_text, session_id = result[0], result[1]
        save_session(session_id)
        send_message(token, chat_id, response_text)


if __name__ == "__main__":
    main()
