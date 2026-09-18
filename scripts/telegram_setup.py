#!/usr/bin/env python3
"""Discover Telegram IDs or save a webhook secret without displaying the bot token."""

import argparse
import json
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from provider_preflight import load_env

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--env-file", type=Path, default=Path(".env"))
parser.add_argument("--generate-secret", action="store_true")
args = parser.parse_args()
if not args.env_file.is_file():
    parser.exit(2, "Env file not found.\n")
if args.generate_secret:
    # Lock the file and only replace a blank assignment; never rotate an existing secret.
    import fcntl

    with args.env_file.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        contents = handle.read()
        match = re.search(r"^ANTON_TELEGRAM_SECRET=(.*)$", contents, re.M)
        if match and match.group(1).strip().strip("\"'"):
            parser.exit(0, "Telegram secret already set; preserved without printing.\n")
        assignment = "ANTON_TELEGRAM_SECRET=" + secrets.token_urlsafe(32)
        contents = (
            contents[: match.start()] + assignment + contents[match.end() :]
            if match
            else contents.rstrip() + "\n" + assignment + "\n"
        )
        handle.seek(0)
        handle.write(contents)
        handle.truncate()
    args.env_file.chmod(0o600)
    print(
        "Telegram secret saved in env file; value not printed. Use this same value for setWebhook secret_token."
    )
    raise SystemExit(0)
env = load_env(args.env_file)
token = env.get("ANTON_TELEGRAM_TOKEN", "")
if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
    parser.exit(2, "Set ANTON_TELEGRAM_TOKEN in the env file first.\n")


def call(method):
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)
        if not data.get("ok"):
            parser.exit(1, "Telegram rejected the request; response omitted.\n")
        return data["result"]
    except urllib.error.HTTPError as error:
        parser.exit(1, f"Telegram returned HTTP {error.code}; response omitted.\n")
    except Exception as error:
        parser.exit(
            1, f"Telegram request failed ({type(error).__name__}); details omitted.\n"
        )


info = call("getWebhookInfo")
if info.get("url"):
    parser.exit(
        1,
        "An existing webhook is active, so getUpdates cannot run. It was left unchanged. Obtain chat/user IDs from that receiver or deliberately remove its webhook before discovery.\n",
    )
updates = call("getUpdates?timeout=0")
seen = set()
for update in updates:
    message = update.get("message") or update.get("edited_message")
    if not message:
        continue
    chat = message.get("chat", {})
    actor = message.get("from", {})
    if actor.get("is_bot"):
        continue
    pair = (chat.get("id"), actor.get("id"))
    if None in pair or pair in seen:
        continue
    seen.add(pair)
    print(
        f"chat_id={pair[0]} user_id={pair[1]} chat_type={chat.get('type', 'unknown')}"
    )
if not seen:
    print(
        "No recent user messages found. Send /start to the bot privately, or /start@YourBotUsername in the target group, then rerun."
    )
print(
    "Choose the intended chat and allowed users. No IDs were automatically trusted; no messages were sent."
)
