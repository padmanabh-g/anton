#!/usr/bin/env python3
"""Read-only provider checks. Never print secrets, bodies, IDs, or exception text."""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values = dict(os.environ)
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            key, sep, value = line.partition("=")
            if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("Invalid env file syntax")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            values[key] = value
    return values


def probe(label, url, headers):
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
        if label == "Telegram" and not data.get("ok"):
            print(f"{label}: API rejected request")
            return
        if label.startswith("GitHub repository"):
            print(
                f"{label}: authenticated; push permission={bool(data.get('permissions', {}).get('push'))}"
            )
        else:
            print(f"{label}: authenticated read succeeded")
    except urllib.error.HTTPError as error:
        print(
            f"{label}: HTTP {error.code}; credential or access configuration required"
        )
    except Exception as error:
        print(f"{label}: {type(error).__name__}; no response details printed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--remote", action="store_true", help="Issue read-only provider API requests"
    )
    args = parser.parse_args()
    try:
        env = load_env(args.env_file)
    except Exception:
        parser.exit(2, "Could not parse env file; no contents printed.\n")
    groups = {
        "ElevenLabs": [
            "ANTON_ELEVENLABS_API_KEY",
            "ANTON_ELEVENLABS_AGENT_ID",
            "ANTON_ELEVENLABS_PHONE_NUMBER_ID",
        ],
        "Devin": ["ANTON_DEVIN_API_KEY"],
        "GitHub": ["ANTON_GITHUB_TOKEN"],
        "Telegram": ["ANTON_TELEGRAM_TOKEN"],
        "Datadog": ["DD_API_KEY", "DD_APP_KEY"],
        "RUM": ["PUBLIC_DD_APPLICATION_ID", "PUBLIC_DD_CLIENT_TOKEN"],
    }
    print("Env file:", "present" if args.env_file.exists() else "absent")
    for label, keys in groups.items():
        present = sum(bool(env.get(key)) for key in keys)
        print(f"{label}: {present}/{len(keys)} expected values present")
    if not args.remote:
        print(
            "Remote checks skipped (use --remote); no calls, messages, sessions or writes are performed."
        )
        return
    if key := env.get("ANTON_ELEVENLABS_API_KEY"):
        probe("ElevenLabs", "https://api.elevenlabs.io/v1/user", {"xi-api-key": key})
    if key := env.get("ANTON_DEVIN_API_KEY"):
        probe(
            "Devin v1",
            "https://api.devin.ai/v1/sessions?limit=1",
            {"Authorization": f"Bearer {key}"},
        )
    if key := env.get("ANTON_GITHUB_TOKEN"):
        for repo in ("anton", "anton-demo-product"):
            probe(
                f"GitHub repository {repo}",
                f"https://api.github.com/repos/padmanabh-g/{repo}",
                {
                    "Authorization": f"Bearer {key}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    if key := env.get("ANTON_TELEGRAM_TOKEN"):
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", key):
            print("Telegram: malformed token; request skipped")
        else:
            probe("Telegram", f"https://api.telegram.org/bot{key}/getMe", {})
    if env.get("DD_API_KEY") and env.get("DD_APP_KEY"):
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
            print("Datadog: unsupported site; request skipped")
        else:
            probe(
                "Datadog API",
                f"https://api.{site}/api/v1/validate",
                {
                    "DD-API-KEY": env["DD_API_KEY"],
                    "DD-APPLICATION-KEY": env["DD_APP_KEY"],
                },
            )


if __name__ == "__main__":
    main()
