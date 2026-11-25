import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

type Profile = Literal["real", "sanal"]
PROFILES: tuple[Profile, ...] = ("real", "sanal")


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
    # K-107: sanal portföy ayrı ve işaretli veritabanında; profil yalnızca buradan seçilir.
    profile: Profile = "real"
    sanal_db_path: Path | None = None
    sanal_portfolio_path: Path | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    evds_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    telegram_base_url: str = "https://api.telegram.org"
    # K-90 ve K-93: Telegram'da TL tutarları varsayılan olarak gizli.
    telegram_hide_amounts: bool = True
    telegram_payday_show_amounts: bool = False
    # K-73: haftalık rapor isteğe bağlı; M4 kabul süresince açılır.
    weekly_report_enabled: bool = False
    # K-84: ping URL'leri sırdır (LoadCredential).
    healthcheck_reports_url: SecretStr | None = None
    healthcheck_backup_url: SecretStr | None = None
    lock_dir: Path | None = None
    # K-82: yalnızca açık anahtarlar (age1…), virgülle ayrılmış; gizli anahtar sunucuda durmaz.
    backup_dir: Path | None = None
    backup_age_recipients: Annotated[list[str], NoDecode] = Field(default_factory=list)
    backup_scratch_dir: Path | None = None
    age_binary: str = "age"
    evds_base_url: str = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
    cpi_series: str = "TP.TUKFIY2025.GENEL"
    cpi_base: str = "2025=100"
    tefas_base_url: str = "https://www.tefas.gov.tr/api/funds/"
    # K-71: istekler arası en az 10 sn; daha kısası kabul edilmez.
    tefas_min_interval_s: int = Field(default=10, ge=10)
    # K-123: web arayüzü; izin verilen tek Tailscale girişi ve POST denetimi için köken.
    web_allowed_login: str | None = None
    web_origin: str | None = None
    web_session_key: SecretStr | None = None
    # K-126: şifrenin scrypt özeti (`ft web sifre`); boşsa web'de yazma kapalıdır.
    web_password: SecretStr | None = None
    web_socket: Path = Path("/run/finans-web/web.sock")

    @field_validator(
        "evds_api_key",
        "telegram_bot_token",
        "telegram_chat_id",
        "healthcheck_reports_url",
        "healthcheck_backup_url",
        "web_allowed_login",
        "web_origin",
        "web_session_key",
        "web_password",
        mode="before",
    )
    @classmethod
    def _blank_key_is_undefined(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("backup_age_recipients", mode="before")
    @classmethod
    def _split_recipients(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def sanal_database(self) -> Path:
        return self.sanal_db_path or self.db_path.parent / "sanal.db"

    @model_validator(mode="after")
    def _sanal_database_is_separate(self) -> Self:
        if self.sanal_database.resolve() == self.db_path.resolve():
            raise ValueError(
                "Sanal veritabanı gerçek veritabanıyla aynı dosya olamaz "
                "(FT_SANAL_DB_PATH ve FT_DB_PATH)."
            )
        return self


def resolve_profile(settings: Settings) -> Settings:
    """Sanal profilde yollar sanal dosyalara çevrilir; kodun geri kalanı profili bilmez."""
    if settings.profile == "real":
        return settings
    locks = settings.lock_dir or settings.db_path.parent / "locks"
    return settings.model_copy(
        update={
            "db_path": settings.sanal_database,
            "portfolio_path": settings.sanal_portfolio_path or settings.portfolio_path,
            "lock_dir": locks / "sanal",
        }
    )


def profile_settings(base: Settings) -> dict[Profile, Settings]:
    """Web iki profili birlikte sunar; `base` profili çözülmemiş ayarlardır (K-125)."""
    return {p: resolve_profile(base.model_copy(update={"profile": p})) for p in PROFILES}


def load_base_settings() -> Settings:
    # systemd LoadCredential sırları bu dizine, ayar adıyla dosya olarak koyar.
    credentials_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials_dir:
        return Settings(_secrets_dir=credentials_dir)
    return Settings()


def load_settings() -> Settings:
    return resolve_profile(load_base_settings())
