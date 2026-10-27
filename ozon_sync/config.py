from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ozon_env: Literal["sandbox", "prod"] = "sandbox"
    ozon_client_id: str = ""
    ozon_api_key: SecretStr = SecretStr("")
    ozon_sandbox_client_id: str = ""
    ozon_sandbox_client_secret: SecretStr = SecretStr("")
    ozon_prod_url: str = "https://api-seller.ozon.ru"
    ozon_sandbox_url: str = "https://api-seller-sandbox.ozon.ru"
    ozon_timeout: float = 30.0
    ozon_max_retries: int = 3
    ozon_max_429_retries: int = 10
    ozon_method_overrides: dict[str, str] = {}

    database_url: str = "postgresql://ozon:ozon@localhost:5432/ozon"
    log_level: str = "INFO"

    sync_schedule: str = "10:00,14:00,18:00"
    sync_timezone: str = "Europe/Moscow"

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    telegram_summary: bool = True
    stale_after_hours: int = 12

    @property
    def schedule_times(self) -> list[tuple[int, int]]:
        times = []
        for part in self.sync_schedule.split(","):
            hour, minute = part.strip().split(":")
            times.append((int(hour), int(minute)))
        return times

    @property
    def ozon_base_url(self) -> str:
        return self.ozon_sandbox_url if self.ozon_env == "sandbox" else self.ozon_prod_url
