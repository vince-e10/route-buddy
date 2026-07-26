import os
from dataclasses import dataclass


SECRET_ENV_VARS = [
    "OPENROUTER_API_KEY",
    "WEBHOOK_SHARED_SECRET",
    "ONEMAP_EMAIL",
    "ONEMAP_PASSWORD",
]


def _bool(value: str) -> bool:
    return value == "1"


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model_primary: str
    openrouter_model_fallback: str
    llm_mode: str
    floci_storage_mode: str
    floci_storage_persistent_path: str
    aws_endpoint_url: str
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_default_region: str
    uber_base_url: str
    uber_api_token: str
    uber_org_uuid: str
    webhook_shared_secret: str
    onemap_base_url: str
    onemap_email: str
    onemap_password: str
    rider_first_name: str
    rider_last_name: str
    rider_phone: str
    sim_speed: float
    mock_deterministic: bool
    webhook_target_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        get = os.getenv
        return cls(
            openrouter_api_key=get("OPENROUTER_API_KEY", ""),
            openrouter_base_url=get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            openrouter_model_primary=get("OPENROUTER_MODEL_PRIMARY", "z-ai/glm-4.5-air"),
            openrouter_model_fallback=get("OPENROUTER_MODEL_FALLBACK", "minimax/minimax-m2"),
            llm_mode=get("LLM_MODE", "openrouter"),
            floci_storage_mode=get("FLOCI_STORAGE_MODE", "persistent"),
            floci_storage_persistent_path=get("FLOCI_STORAGE_PERSISTENT_PATH", "/app/data"),
            aws_endpoint_url=get("AWS_ENDPOINT_URL", "http://floci:4566"),
            aws_access_key_id=get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=get("AWS_SECRET_ACCESS_KEY", "test"),
            aws_default_region=get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            uber_base_url=get("UBER_BASE_URL", "http://mock-uber:8001"),
            uber_api_token=get("UBER_API_TOKEN", "mock-token"),
            uber_org_uuid=get("UBER_ORG_UUID", "mock-org-uuid"),
            webhook_shared_secret=get("WEBHOOK_SHARED_SECRET", ""),
            onemap_base_url=get("ONEMAP_BASE_URL", "https://www.onemap.gov.sg"),
            onemap_email=get("ONEMAP_EMAIL", ""),
            onemap_password=get("ONEMAP_PASSWORD", ""),
            rider_first_name=get("RIDER_FIRST_NAME", "Demo"),
            rider_last_name=get("RIDER_LAST_NAME", "Rider"),
            rider_phone=get("RIDER_PHONE", "+6591234567"),
            sim_speed=float(get("SIM_SPEED", "1.0")),
            mock_deterministic=_bool(get("MOCK_DETERMINISTIC", "0")),
            webhook_target_url=get("WEBHOOK_TARGET_URL", "http://api:8000/webhooks/uber"),
        )

    @property
    def secret_values(self) -> list[str]:
        return [
            value
            for value in [
                self.aws_access_key_id,
                self.aws_secret_access_key,
                self.uber_api_token,
                self.openrouter_api_key,
                self.webhook_shared_secret,
                self.onemap_email,
                self.onemap_password,
            ]
            if value != "test"
        ]


settings = Settings.from_env()
