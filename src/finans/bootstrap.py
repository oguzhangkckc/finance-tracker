import logging
import os
import secrets
import shutil
import socket
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from finans.adapters._http import HttpClient
from finans.adapters.age import AgeEncryptor
from finans.adapters.clock import SystemClock
from finans.adapters.csv_statement import CsvStatementFile
from finans.adapters.csv_transactions import CsvTransactionFile
from finans.adapters.evds import EvdsCpiSource
from finans.adapters.healthcheck import HealthcheckPing
from finans.adapters.json_log import JsonFormatter
from finans.adapters.lock import FlockJobLock
from finans.adapters.portfolio_toml import TomlPortfolioSource
from finans.adapters.render.json import JsonRenderer
from finans.adapters.render.text import TextRenderer
from finans.adapters.sqlite.connection import (
    ProfileError,
    create_sanal,
    is_sanal,
    sqlite_version,
)
from finans.adapters.sqlite.migrate import (
    MigrationError,
    MigrationRun,
    SchemaStatus,
    bundled,
    migrate,
    schema_status,
)
from finans.adapters.sqlite.snapshot import SqliteCopier
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.adapters.tefas import TefasPriceSource
from finans.adapters.telegram import TelegramNotifier
from finans.adapters.unix_listener import listen_unix
from finans.application.backup import (
    REAL_PREFIX,
    SANAL_PREFIX,
    BackupOutcome,
    create_backup,
    files_with_secret_keys,
    recipient_problems,
)
from finans.application.doctor import (
    Check,
    cpi_check,
    inactive_holdings_check,
    portfolio_checks,
    price_check,
)
from finans.application.jobs import JobContext, JobOutcome, job_body, run_job
from finans.contracts.report import SANAL_NOTICE
from finans.domain.portfolio import ConfigError, PortfolioConfig
from finans.ports.clock import Clock
from finans.ports.notifier import Notifier, NotifyError
from finans.ports.render import ReportRenderer
from finans.ports.sources import (
    CpiSource,
    PortfolioConfigSource,
    PriceSource,
    SourceError,
    StatementFile,
    TransactionFile,
)
from finans.ports.unit_of_work import UnitOfWork
from finans.settings import Settings

__all__ = [
    "MigrationError",
    "MigrationRun",
    "NotifyError",
    "ProfileError",
    "SetupError",
    "SourceError",
    "configure_logging",
    "cpi_source",
    "is_sanal_profile",
    "migrate_database",
    "notifier",
    "open_unit_of_work",
    "portfolio_source",
    "price_source",
    "report_renderer",
    "require_sanal",
    "run_doctor",
    "run_scheduled_job",
    "sanal_init",
    "sanal_reset",
    "statement_file",
    "system_clock",
    "telegram_renderer",
    "transaction_file",
    "web_listener",
]


MIGRATION_BACKUPS_KEPT = 5


class SetupError(Exception):
    pass


def is_sanal_profile(settings: Settings) -> bool:
    return settings.profile == "sanal"


def migrate_database(settings: Settings, clock: Clock | None = None) -> MigrationRun:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return migrate(
        settings.db_path,
        bundled(),
        clock=clock or SystemClock(),
        backup_dir=settings.db_path.parent / "backups",
        keep_backups=MIGRATION_BACKUPS_KEPT,
        sanal=is_sanal_profile(settings),
    )


def open_unit_of_work(settings: Settings, *, readonly: bool = False) -> UnitOfWork:
    sanal = is_sanal_profile(settings)
    if readonly:
        if not settings.db_path.exists():
            first = "ft sanal init" if sanal else "ft db migrate"
            raise SetupError(
                f"Veritabanı bulunamadı ({settings.db_path}); önce `{first}` çalıştır."
            )
        # Salt okunur açılış migration çalıştırmaz; eski şemada yeni sütunlar okunamaz.
        status = schema_status(settings.db_path, sanal=sanal)
        if status.current != status.latest:
            raise SetupError(
                f"Veritabanı şeması güncel değil (sürüm {status.current}, en son "
                f"{status.latest}); `ft db migrate` çalıştır."
            )
    else:
        migrate_database(settings)
    return SqliteUnitOfWork(settings.db_path, readonly=readonly, sanal=sanal)


def require_sanal(settings: Settings) -> None:
    if not is_sanal_profile(settings):
        raise SetupError("Bu işlem yalnızca sanal profilde yapılır: FT_PROFILE=sanal.")


def sanal_init(settings: Settings, clock: Clock | None = None) -> MigrationRun:
    """İşaret şemadan önce yazılır; işaretsiz bir sanal dosya hiçbir anda oluşmaz (K-107)."""
    require_sanal(settings)
    create_sanal(settings.db_path)
    return migrate_database(settings, clock)


def sanal_reset(settings: Settings) -> list[Path]:
    require_sanal(settings)
    database = settings.db_path
    if not database.exists():
        raise SetupError(f"Sanal veritabanı yok ({database}); silinecek bir şey yok.")
    if not is_sanal(database):
        raise ProfileError(f"{database} sanal olarak işaretli değil; silinmedi.")
    removed = []
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


@contextmanager
def cpi_source(settings: Settings, clock: Clock) -> Iterator[CpiSource]:
    if settings.evds_api_key is None:
        raise SetupError(
            "FT_EVDS_API_KEY tanımlı değil; EVDS3 hesabındaki API anahtarını .env'e "
            "(üretimde LoadCredential ile) ekle."
        )
    key = settings.evds_api_key.get_secret_value()
    with HttpClient(clock, secrets=[key]) as http:
        yield EvdsCpiSource(http, api_key=key, base_url=settings.evds_base_url, clock=clock)


@contextmanager
def price_source(settings: Settings, clock: Clock) -> Iterator[PriceSource]:
    with HttpClient(
        clock, min_interval=settings.tefas_min_interval_s, jitter=_tefas_jitter
    ) as http:
        yield TefasPriceSource(http, base_url=settings.tefas_base_url, clock=clock)


def _tefas_jitter() -> int:
    return secrets.randbelow(3)


def portfolio_source() -> PortfolioConfigSource:
    return TomlPortfolioSource()


def system_clock() -> Clock:
    return SystemClock()


@contextmanager
def notifier(settings: Settings, clock: Clock) -> Iterator[Notifier]:
    token = settings.telegram_bot_token
    if token is None or settings.telegram_chat_id is None:
        raise SetupError(
            "FT_TELEGRAM_BOT_TOKEN ve FT_TELEGRAM_CHAT_ID tanımlı olmalı; botu ve sohbet "
            "ID'sini sen oluşturup .env'e (üretimde LoadCredential ile) eklersin (K-89)."
        )
    secret = token.get_secret_value()
    with HttpClient(clock, secrets=[secret]) as http:
        yield TelegramNotifier(
            http,
            token=secret,
            chat_id=settings.telegram_chat_id,
            base_url=settings.telegram_base_url,
            prefix=f"\U0001f9ea {SANAL_NOTICE}" if is_sanal_profile(settings) else None,
        )


def configure_logging(settings: Settings) -> None:
    """İşler stderr'e JSON satırı yazar; systemd bunu journald'a aktarır (K-81)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def run_scheduled_job(settings: Settings, clock: Clock, job: str, logical_date: date) -> JobOutcome:
    if settings.portfolio_path is None:
        raise SetupError("FT_PORTFOLIO_PATH tanımlı değil; işler portföy dosyasına ihtiyaç duyar.")
    config = portfolio_source().load(settings.portfolio_path)
    hidden = [
        secret.get_secret_value()
        for secret in (
            settings.evds_api_key,
            settings.telegram_bot_token,
            settings.healthcheck_reports_url,
            settings.healthcheck_backup_url,
        )
        if secret is not None
    ]
    telegram = settings.telegram_bot_token is not None and settings.telegram_chat_id is not None
    context = JobContext(
        config=config,
        open_uow=lambda: open_unit_of_work(settings),
        clock=clock,
        cpi_series=settings.cpi_series,
        cpi_base=settings.cpi_base,
        price_source=lambda: price_source(settings, clock),
        cpi_source=lambda: cpi_source(settings, clock),
        notifier=(lambda: notifier(settings, clock)) if telegram else None,
        renderer=telegram_renderer(settings),
        weekly_enabled=settings.weekly_report_enabled,
        backup=_backup_factory(settings),
        profile=settings.profile,
    )
    # K-110: ping'ler yalnızca gerçek sistemin sağlığını gösterir; sanal profil ping atmaz.
    urls = (
        {}
        if is_sanal_profile(settings)
        else {
            check: url.get_secret_value()
            for check, url in (
                ("reports", settings.healthcheck_reports_url),
                ("backup", settings.healthcheck_backup_url),
            )
            if url is not None
        }
    )
    lock = FlockJobLock(settings.lock_dir or settings.db_path.parent / "locks")
    with HttpClient(clock, secrets=list(urls.values())) as http:
        return run_job(
            job,
            logical_date,
            job_body(job, logical_date, context),
            open_uow=lambda: open_unit_of_work(settings),
            lock=lock,
            clock=clock,
            ping=HealthcheckPing(http, urls),
            secrets=hidden,
        )


def telegram_renderer(settings: Settings) -> ReportRenderer:
    return TextRenderer(
        hide_amounts=settings.telegram_hide_amounts,
        payday_amounts=settings.telegram_payday_show_amounts,
        html=True,
    )


def report_renderer(
    fmt: str = "text", *, hide_amounts: bool = False, payday_amounts: bool = True
) -> ReportRenderer:
    if fmt == "json":
        return JsonRenderer()
    return TextRenderer(hide_amounts=hide_amounts, payday_amounts=payday_amounts)


def statement_file() -> StatementFile:
    return CsvStatementFile()


def transaction_file() -> TransactionFile:
    return CsvTransactionFile()


def run_doctor(settings: Settings) -> list[Check]:
    version, supported = sqlite_version()
    checks = [Check("SQLite", "ok" if supported else "fail", version)]
    schema_ok = False
    sanal = is_sanal_profile(settings)
    if not settings.db_path.exists():
        first = "ft sanal init" if sanal else "ft db migrate"
        checks.append(Check("Veritabanı şeması", "fail", f"veritabanı yok; `{first}` çalıştır"))
    else:
        try:
            status = schema_status(settings.db_path, sanal=sanal)
        except ProfileError as exc:
            checks.append(Check("Veritabanı profili", "fail", str(exc)))
        else:
            checks.append(_schema_check(status))
            schema_ok = checks[-1].status == "ok"
    config = _config_check(settings, checks)
    if schema_ok:
        with open_unit_of_work(settings, readonly=True) as uow:
            if config is None:
                checks.append(inactive_holdings_check(uow))
            else:
                checks.extend(portfolio_checks(uow, config))
            today = SystemClock().today()
            checks.append(price_check(uow, today=today))
            checks.append(cpi_check(uow, settings.cpi_series, today=today))
    checks.append(_evds_key_check(settings))
    checks.append(_telegram_check(settings))
    checks.extend(_backup_checks(settings, Path(".env")))
    checks.append(_env_check(Path(".env")))
    return checks


def _schema_check(status: SchemaStatus) -> Check:
    if status.current == status.latest:
        return Check("Veritabanı şeması", "ok", f"güncel (sürüm {status.current})")
    if status.current < status.latest:
        detail = f"sürüm {status.current}, en son {status.latest}; `ft db migrate` çalıştır"
        return Check("Veritabanı şeması", "warn", detail)
    detail = f"veritabanı sürümü ({status.current}) koddan ({status.latest}) yeni"
    return Check("Veritabanı şeması", "fail", detail)


def _config_check(settings: Settings, checks: list[Check]) -> PortfolioConfig | None:
    if settings.portfolio_path is None:
        checks.append(Check("Config", "warn", "FT_PORTFOLIO_PATH ayarlı değil"))
        return None
    try:
        config = portfolio_source().load(settings.portfolio_path)
    except ConfigError as exc:
        checks.append(
            Check("Config", "fail", f"{len(exc.issues)} hata; ayrıntı için `ft config check`")
        )
        return None
    checks.append(
        Check(
            "Config", "ok", f"{len(config.instruments)} varlık, {len(config.targets)} hedef sınıf"
        )
    )
    return config


def _telegram_check(settings: Settings) -> Check:
    if settings.telegram_bot_token is None or settings.telegram_chat_id is None:
        return Check(
            "Telegram",
            "warn",
            "FT_TELEGRAM_BOT_TOKEN ya da FT_TELEGRAM_CHAT_ID tanımlı değil; bildirim gönderilemez",
        )
    return Check("Telegram", "ok", "token ve sohbet ID'si tanımlı")


def _evds_key_check(settings: Settings) -> Check:
    if settings.evds_api_key is None:
        return Check("EVDS anahtarı", "warn", "FT_EVDS_API_KEY tanımlı değil")
    return Check("EVDS anahtarı", "ok", "tanımlı")


def _backup_factory(settings: Settings) -> Callable[[datetime], BackupOutcome] | None:
    directory = settings.backup_dir
    if directory is None or not settings.backup_age_recipients:
        return None
    scratch = settings.backup_scratch_dir or settings.db_path.parent

    def backup(now: datetime) -> BackupOutcome:
        return create_backup(
            copier=SqliteCopier(settings.db_path, sanal=is_sanal_profile(settings)),
            encryptor=AgeEncryptor(settings.age_binary),
            recipients=settings.backup_age_recipients,
            directory=directory,
            scratch_parent=scratch,
            now=now,
            prefix=SANAL_PREFIX if is_sanal_profile(settings) else REAL_PREFIX,
        )

    return backup


def _backup_checks(settings: Settings, env: Path) -> list[Check]:
    """age gizli anahtarı sunucuda durmaz; yalnızca açık anahtarlar tanımlıdır (K-82)."""
    if settings.backup_dir is None or not settings.backup_age_recipients:
        setup = Check(
            "Yedek",
            "warn",
            "FT_BACKUP_DIR ya da FT_BACKUP_AGE_RECIPIENTS tanımlı değil; gece yedeği alınamaz",
        )
    elif problems := recipient_problems(settings.backup_age_recipients):
        setup = Check("Yedek", "fail", "; ".join(problems))
    elif shutil.which(settings.age_binary) is None:
        setup = Check("Yedek", "warn", f"{settings.age_binary} bulunamadı; age paketini kur")
    else:
        count = len(settings.backup_age_recipients)
        setup = Check("Yedek", "ok", f"{count} alıcı (açık anahtar), dizin {settings.backup_dir}")
    places = [env] + [
        Path(path)
        for path in (os.environ.get("CREDENTIALS_DIRECTORY"), settings.backup_dir)
        if path is not None
    ]
    found = files_with_secret_keys([place for place in places if place.exists()])
    secret = (
        Check(
            "age gizli anahtarı",
            "fail",
            "sunucuda bulundu, kaldır: " + ", ".join(str(path) for path in found),
        )
        if found
        else Check("age gizli anahtarı", "ok", "sunucuda yok (.env, credentials, yedek dizini)")
    )
    return [setup, secret]


def _env_check(path: Path) -> Check:
    if not path.exists():
        return Check(".env izinleri", "ok", "dosya yok")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return Check(".env izinleri", "warn", f"{mode:o}; 600 olmalı (chmod 600 .env)")
    return Check(".env izinleri", "ok", f"{mode:o}")


def web_listener(settings: Settings) -> socket.socket:
    """finans-web'in dinlediği tek yer: 0600 izinli Unix soketi, TCP yok (K-101, K-123)."""
    return listen_unix(settings.web_socket)
