import os
from pathlib import Path
from typing import Literal

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


def load_settings() -> Settings:
    # systemd LoadCredential sırları bu dizine, ayar adıyla dosya olarak koyar.
    credentials_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials_dir:
        return Settings(_secrets_dir=credentials_dir)
    return Settings()
