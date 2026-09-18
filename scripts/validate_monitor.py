#!/usr/bin/env python3
"""Validate (never create) the PRD's one-minute Datadog RUM monitor."""

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from provider_preflight import load_env

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--env-file", type=Path, default=Path(".env"))
args = parser.parse_args()
env = load_env(args.env_file)
site = env.get("DD_SITE", "datadoghq.com")
if site not in {
    "datadoghq.com",
    "datadoghq.eu",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "ap1.datadoghq.com",
    "ap2.datadoghq.com",
    "ddog-gov.com",
}:
    parser.exit(2, "Unsupported Datadog site.\n")
run = env.get("PUBLIC_DEMO_RUN_ID", "")
if (
    not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run)
    or not env.get("DD_API_KEY")
    or not env.get("DD_APP_KEY")
):
    parser.exit(2, "Set DD_API_KEY, DD_APP_KEY and a safe PUBLIC_DEMO_RUN_ID first.\n")
query = (
    'rum("@type:error service:midnight-bento env:demo @context.error_code:checkout_minimum @context.run_id:'
    + run
    + '").rollup("count").last("1m") >= 5'
)
body = {
    "name": "Anton checkout validation rehearsal",
    "type": "rum alert",
    "query": query,
    "message": "Validation only; no monitor created.",
    "options": {
        "thresholds": {"critical": 5},
        "include_tags": True,
        "enable_logs_sample": False,
    },
}
request = urllib.request.Request(
    f"https://api.{site}/api/v1/monitor/validate",
    data=json.dumps(body).encode(),
    headers={
        "Content-Type": "application/json",
        "DD-API-KEY": env["DD_API_KEY"],
        "DD-APPLICATION-KEY": env["DD_APP_KEY"],
    },
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        print("Monitor validation accepted:", response.status)
    print("Validated query:", query)
    print(
        "No monitor was created. Record the actual deployed query and measured latency during rehearsal."
    )
except urllib.error.HTTPError as error:
    print("Monitor validation rejected: HTTP", error.code)
    print(
        "No monitor was created. Inspect the Datadog UI for the account-specific constraint; do not silently widen the PRD window."
    )
    raise SystemExit(1)
except Exception as error:
    print("Monitor validation unavailable:", type(error).__name__)
    raise SystemExit(1)
