from anton.config import Settings
from anton.summaries import session_summary


def test_provider_details_are_bounded_redacted_and_field_allowlisted():
    settings = Settings(
        devin_api_key="devin-test-key-known",
        telegram_token="12345678:telegram-test-token",
    )
    result = session_summary(
        {
            "structured_output": {
                "input_needed": "Grant repo access; token=unknown-credential. Devin key devin-test-key-known; Authorization: Bearer another-secret. https://service.test/?key=url-secret",
                "failure_reason": "Private key: -----BEGIN PRIVATE KEY-----\nsecret-body\n-----END PRIVATE KEY-----",
                "change_summary": "a" * 2000,
                "validation_summary": ["invalid-type"],
                "secret_dump": "must never copy",
            }
        },
        settings,
    )
    text = str(result)
    assert "Grant repo access" in text
    for forbidden in (
        "unknown-credential",
        "devin-test-key-known",
        "another-secret",
        "url-secret",
        "secret-body",
        "must never copy",
    ):
        assert forbidden not in text
    assert len(result["change_summary"]) <= 800
    assert result["validation_summary"] == ""
