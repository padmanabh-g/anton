#!/usr/bin/env python3
"""Authenticated explicit operator actions. Does not print or pass secrets in URLs."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--env-file")
parser.add_argument(
    "command",
    choices=[
        "incidents",
        "incident",
        "reset",
        "resume",
        "retry-call",
        "reconcile",
        "cancel-strategy",
        "record-outcome",
    ],
)
parser.add_argument("arguments", nargs="*")
args = parser.parse_args()
if args.env_file:
    from dotenv import load_dotenv

    load_dotenv(args.env_file)
secret = os.environ.get("ANTON_OPERATOR_SECRET")
if not secret:
    sys.exit("ANTON_OPERATOR_SECRET is required")
command = args.command
values = args.arguments
data = None
try:
    if command == "incidents":
        path = "/operator/incidents"
    elif command == "incident":
        path = "/operator/incidents/" + values[0]
    elif command == "reset":
        path = "/operator/reset"
        data = {"run_id": values[0]}
    elif command == "resume":
        path = "/operator/incidents/" + values[0] + "/resume"
        data = {}
    elif command == "retry-call":
        path = "/operator/incidents/" + values[0] + "/retry-call"
        data = {"purpose": values[1]}
    elif command == "cancel-strategy":
        path = "/operator/incidents/" + values[0] + "/cancel-strategy"
        data = {"evidence": values[1]}
    elif command == "record-outcome":
        path = "/operator/actions/" + values[0] + "/record-outcome"
        data = {"status": values[1], "evidence": values[2]}
    else:
        path = "/operator/actions/" + values[0] + "/reconcile"
        data = {"provider_id": values[1], "evidence": values[2]}
except IndexError:
    sys.exit("Missing positional arguments; see docs/OPERATIONS.md")
if not args.url.startswith("https://") and not args.url.startswith("http://127.0.0.1:"):
    sys.exit("Use HTTPS, or explicit loopback for local development")
request = urllib.request.Request(
    args.url.rstrip("/") + path,
    data=json.dumps(data).encode() if data is not None else None,
    headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        print(json.dumps(json.load(response), indent=2))
except urllib.error.HTTPError as e:
    sys.exit(
        "Operator request failed, HTTP " + str(e.code) + ": " + e.read().decode()[:1000]
    )
