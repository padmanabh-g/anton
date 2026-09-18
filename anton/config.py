import os
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/anton.db"
    run_id: str = "unconfigured"
    repository: str = "padmanabh-g/anton-demo-product"
    base_branch: str = "demo/buggy"
    deployed_sha: str = ""
    seed_regression_sha: str = ""
    known_good_sha: str = ""
    datadog_secret: str = ""
    voice_secret: str = ""
    operator_secret: str = ""
    telegram_secret: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_user_ids: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_phone_number_id: str = ""
    elevenlabs_webhook_secret: str = ""
    responder_number: str = ""
    responder_id: str = "oncall"
    devin_api_key: str = ""
    github_token: str = ""
    github_check_name: str = "checkout-regression"
    github_check_app_id: str = "15368"
    worker_enabled: str = "true"
    regression_path: str = "src/lib/checkout.ts"

    @classmethod
    def from_env(cls):
        return cls(
            **{
                f.name: os.environ["ANTON_" + f.name.upper()]
                for f in fields(cls)
                if "ANTON_" + f.name.upper() in os.environ
            }
        )
