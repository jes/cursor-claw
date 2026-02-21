#!/usr/bin/env python3
"""
Poll Telegram Bot API and print user IDs that send messages.
Usage: TELEGRAM_BOT_TOKEN=<your_token> python3 echo_user_ids.py

Send a message to your bot; this script will print your user ID. Do not commit
the bot token; use the env var only.
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error

BASE = "https://api.telegram.org/bot"


def get_token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN and run again.", file=sys.stderr)
        sys.exit(1)
    return token


def api(token, method, **params):
    url = f"{BASE}{token}/{method}"
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    token = get_token()
    offset = 0
    print("Listening for messages. Send a message to your bot; this will print your user ID.", file=sys.stderr)
    print("Ctrl+C to stop.", file=sys.stderr)
    while True:
        try:
            out = api(token, "getUpdates", offset=offset, timeout=30)
        except urllib.error.URLError as e:
            print(f"API error: {e}", file=sys.stderr)
            time.sleep(5)
            continue
        if not out.get("ok"):
            print(f"API not ok: {out}", file=sys.stderr)
            time.sleep(5)
            continue
        for upd in out.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            user = msg.get("from") or {}
            uid = user.get("id")
            username = user.get("username", "")
            text = (msg.get("text") or "").strip()
            print(f"user_id={uid} username={username!r} text={text[:80]!r}")


if __name__ == "__main__":
    main()
