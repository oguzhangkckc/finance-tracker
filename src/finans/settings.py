import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    db_path: Path
    portfolio_path: Path | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    evds_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    telegram_base_url: str = "https://api.telegram.org"
    # K-90 ve K-93: Telegram'da TL tutarları varsayılan olarak gizli.
    telegram_hide_amounts: bool = True
    telegram_payday_show_amounts: bool = False
    evds_base_url: str = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
    cpi_series: str = "TP.TUKFIY2025.GENEL"
    cpi_base: str = "2025=100"
    tefas_base_url: str = "https://www.tefas.gov.tr/api/funds/"
    # K-71: istekler arası en az 10 sn; daha kısası kabul edilmez.
    tefas_min_interval_s: int = Field(default=10, ge=10)

    @field_validator("evds_api_key", "telegram_bot_token", "telegram_chat_id", mode="before")
    @classmethod
    def _blank_key_is_undefined(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


def load_settings() -> Settings:
    # systemd LoadCredential sırları bu dizine, ayar adıyla dosya olarak koyar.
    credentials_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials_dir:
        return Settings(_secrets_dir=credentials_dir)
    return Settings()
