"""Bounded display of provider-authored progress; never an authorization input."""

import re
from dataclasses import fields

OUTPUT_FIELDS = {
    "input_needed": "Specific non-secret input or permission needed from the operator; empty when none.",
    "failure_reason": "Specific observed reason for failure or expiration; empty when unknown or not failed.",
    "change_summary": "Short factual summary of actual code changes; empty if not established.",
    "validation_summary": "Actual commands and observed validation results, including failures; never invent passing checks.",
}
DEVIN_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        name: {
            "type": "string",
            "maxLength": 1000,
            "description": description
            + " Never include credentials, secret values, environment dumps or raw logs.",
        }
        for name, description in OUTPUT_FIELDS.items()
    },
    "required": list(OUTPUT_FIELDS),
}


def session_summary(session, settings):
    """Only approved string fields, redacted before truncation or persistence.

    Provider prose is evidence attributed to Devin, not trusted instructions. The
    schema asks for no secrets; known runtime credentials and common credential
    forms are additionally removed. Entire URLs and private-key blocks are omitted.
    """
    structured = session.get("structured_output")
    if not isinstance(structured, dict):
        structured = {}
    secrets = [
        getattr(settings, field.name)
        for field in fields(settings)
        if ("secret" in field.name or field.name.endswith(("_token", "_api_key")))
        and getattr(settings, field.name)
    ]
    summaries = {}
    for name in OUTPUT_FIELDS:
        value = structured.get(name)
        if not isinstance(value, str):
            summaries[name] = ""
            continue
        # Reject enormous/unbounded provider fields instead of processing log dumps.
        if len(value) > 10000:
            summaries[name] = "[Provider detail omitted: exceeds safe display limit]"
            continue
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        value = re.sub(
            r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)",
            "[private key omitted]",
            value,
            flags=re.S,
        )
        value = re.sub(r"https?://\S+", "[URL omitted]", value)
        value = re.sub(
            r"(?i)\b(?:bearer|basic)\s+\S+", "[authorization omitted]", value
        )
        value = re.sub(
            r"(?i)\b(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|token|secret|password)\s*[=:]\s*[\"\']?[^\s,;\"\']+",
            "[credential omitted]",
            value,
        )
        value = re.sub(
            r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk[-_][A-Za-z0-9_-]+|\d{6,}:[A-Za-z0-9_-]{12,})\b",
            "[credential omitted]",
            value,
        )
        value = " ".join(value.split())
        summaries[name] = value[:797] + "..." if len(value) > 800 else value
    return summaries


def summary_lines(summary):
    labels = {
        "input_needed": "Input needed",
        "failure_reason": "Failure reason",
        "change_summary": "Changes reported by Devin",
        "validation_summary": "Validation reported by Devin",
    }
    return "\n".join(
        labels[name] + ": " + summary[name]
        for name in OUTPUT_FIELDS
        if summary.get(name)
    )
