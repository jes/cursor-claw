#!/usr/bin/env python3
"""
Telegram bot: only accepts messages from the allowed user (see config); forwards
them to Cursor agent and sends the agent's response back. Uses --output-format json
and --resume to keep one conversation session across restarts (session_id stored in
.cursor_agent_session). All other users are dropped.

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

BASE = "https://api.telegram.org/bot"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config")
SESSION_FILE = os.path.join(SCRIPT_DIR, ".cursor_agent_session")


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
    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
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
        return "Agent timed out after 5 minutes.", resume_session
    except Exception as e:
        return "Error running agent: %s" % e, resume_session


def main():
    token, allowed_user_id = load_config()
    offset = 0
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
        for upd in out.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            uid = (msg.get("from") or {}).get("id")
            if uid != allowed_user_id:
                continue
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            if not text:
                send_message(token, chat_id, "(Send a text message to run the agent.)")
                continue
            send_chat_action(token, chat_id, "typing")
            print("Running agent for prompt: %s..." % text[:60], file=sys.stderr)
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
