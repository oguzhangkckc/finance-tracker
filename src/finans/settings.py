import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

type Profile = Literal["real", "sanal"]
PROFILES: tuple[Profile, ...] = ("real", "sanal")
DEFAULT_WEB_HOST: Final = "127.0.0.1"
MAX_PORT: Final = 65535
MIN_CONFIRM_KEY: Final = 32
MIGRATION_BACKUPS: Final = "migration-backups"
_DIGITS: Final = re.compile(r"[0-9]{1,5}")
# Anahtarlar bu alandan çekildiği için başka bir alan adı kabul edilmez (K-136).
_TEAM_DOMAIN: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com")
_AUDIENCE: Final = re.compile(r"[!-~]+")
_EMAIL: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


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
    # K-136: JSON API; ham metin, çünkü yalnız API ister ve denetler (api_settings), ft etkilenmez.
    web_host: str | None = None
    web_port: str | None = None
    cf_access_team_domain: str | None = None
    cf_access_aud: str | None = None
    web_allowed_email: str | None = None

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
        "web_host",
        "web_port",
        "cf_access_team_domain",
        "cf_access_aud",
        "web_allowed_email",
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

    @property
    def migration_backup_dir(self) -> Path:
        """Migration öncesi şifresiz kopyalar (K-55, K-142); sanal profilde sanal veritabanının
        yanı, çünkü resolve_profile db_path'i çevirir."""
        return self.db_path.parent / MIGRATION_BACKUPS

    @model_validator(mode="after")
    def _sanal_database_is_separate(self) -> Self:
        if self.sanal_database.resolve() == self.db_path.resolve():
            raise ValueError(
                "Sanal veritabanı gerçek veritabanıyla aynı dosya olamaz "
                "(FT_SANAL_DB_PATH ve FT_DB_PATH)."
            )
        return self

    @model_validator(mode="after")
    def _nightly_backups_stay_apart(self) -> Self:
        # Mac yedek dizinini çeker; migration öncesi şifresiz kopya oraya karışmamalı (K-142).
        if self.backup_dir is None:
            return self
        nightly = self.backup_dir.resolve()
        for database in (self.db_path, self.sanal_database):
            copies = (database.parent / MIGRATION_BACKUPS).resolve()
            if nightly.is_relative_to(copies) or copies.is_relative_to(nightly):
                raise ValueError(
                    f"FT_BACKUP_DIR migration öncesi kopyaların dizini ({copies}) olamaz, onu "
                    "içeremez ve onun içinde olamaz: yedek dizini Mac'e çekilir ve yalnız şifreli "
                    "yedek tutar (K-142)."
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


class ApiSettingsError(ValueError):
    """API'nin ayarları eksik ya da geçersiz; API açılmaz (K-136)."""


@dataclass(frozen=True, slots=True)
class ApiSettings:
    host: str
    port: int
    team_domain: str
    audience: str
    allowed_email: str
    origin: str
    # Onay jetonunun HMAC anahtarı (K-137); SecretStr, yazdırılınca değeri görünmez.
    confirm_key: SecretStr

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}"


def api_settings(base: Settings) -> ApiSettings:
    """Bütün sorunlar birlikte bildirilir; değerler iletiye yazılmaz (K-47, K-136)."""
    problems: list[str] = []
    host = (base.web_host or "").strip() or DEFAULT_WEB_HOST
    if not _is_loopback(host):
        problems.append("FT_WEB_HOST yalnız loopback adresi olabilir (127.0.0.1 ya da ::1)")
    port = _port((base.web_port or "").strip())
    if port is None:
        problems.append("FT_WEB_PORT 1 ile 65535 arasında bir sayı olmalı")
    team = (base.cf_access_team_domain or "").strip().lower()
    if not _TEAM_DOMAIN.fullmatch(team):
        problems.append("FT_CF_ACCESS_TEAM_DOMAIN <takım>.cloudflareaccess.com biçiminde olmalı")
    audience = (base.cf_access_aud or "").strip()
    if not _AUDIENCE.fullmatch(audience):
        problems.append("FT_CF_ACCESS_AUD Access uygulamasının AUD etiketi olmalı (boşluksuz)")
    email = (base.web_allowed_email or "").strip()
    if not _EMAIL.fullmatch(email):
        problems.append("FT_WEB_ALLOWED_EMAIL bir e-posta adresi olmalı")
    origin = _origin(base.web_origin or "")
    if origin is None:
        problems.append("FT_WEB_ORIGIN https://<alan adı> biçiminde olmalı (yol yok)")
    key = base.web_session_key
    if key is None or len(key.get_secret_value()) < MIN_CONFIRM_KEY:
        problems.append(
            f"FT_WEB_SESSION_KEY (credstore'da ft_web_session_key) en az {MIN_CONFIRM_KEY} "
            "karakter olmalı"
        )
    if problems or port is None or origin is None or key is None:
        raise ApiSettingsError(f"API başlamaz (K-136): {'; '.join(problems)}.")
    return ApiSettings(host, port, team, audience, email, origin, key)


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _port(text: str) -> int | None:
    if not _DIGITS.fullmatch(text):
        return None
    port = int(text)
    return port if 1 <= port <= MAX_PORT else None


def _origin(text: str) -> str | None:
    """Tarayıcı `Origin`'i sondaki eğik çizgi olmadan ve küçük harfle gönderir."""
    origin = text.strip().rstrip("/").lower()
    parts = urlsplit(origin)
    try:
        parts.port  # noqa: B018 - geçersiz port burada ValueError verir
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    if parts.path or parts.query or parts.fragment:
        return None
    return origin
