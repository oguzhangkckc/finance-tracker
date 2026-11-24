import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from finans.adapters._http import HttpClient
from finans.adapters.clock import SystemClock
from finans.adapters.csv_statement import CsvStatementFile
from finans.adapters.csv_transactions import CsvTransactionFile
from finans.adapters.evds import EvdsCpiSource
from finans.adapters.portfolio_toml import TomlPortfolioSource
from finans.adapters.sqlite.connection import sqlite_version
from finans.adapters.sqlite.migrate import (
    MigrationError,
    MigrationRun,
    bundled,
    migrate,
    schema_status,
)
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.adapters.tefas import TefasPriceSource
from finans.application.doctor import (
    Check,
    cpi_check,
    inactive_holdings_check,
    portfolio_checks,
    price_check,
)
from finans.domain.portfolio import ConfigError, PortfolioConfig
from finans.ports.clock import Clock
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
    "SetupError",
    "SourceError",
    "cpi_source",
    "migrate_database",
    "open_unit_of_work",
    "portfolio_source",
    "price_source",
    "run_doctor",
    "statement_file",
    "system_clock",
    "transaction_file",
]


MIGRATION_BACKUPS_KEPT = 5


class SetupError(Exception):
    pass


def migrate_database(settings: Settings, clock: Clock | None = None) -> MigrationRun:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return migrate(
        settings.db_path,
        bundled(),
        clock=clock or SystemClock(),
        backup_dir=settings.db_path.parent / "backups",
        keep_backups=MIGRATION_BACKUPS_KEPT,
    )


def open_unit_of_work(settings: Settings, *, readonly: bool = False) -> UnitOfWork:
    if readonly:
        if not settings.db_path.exists():
            raise SetupError(
                f"Veritabanı bulunamadı ({settings.db_path}); önce `ft db migrate` çalıştır."
            )
        # Salt okunur açılış migration çalıştırmaz; eski şemada yeni sütunlar okunamaz.
        status = schema_status(settings.db_path)
        if status.current != status.latest:
            raise SetupError(
                f"Veritabanı şeması güncel değil (sürüm {status.current}, en son "
                f"{status.latest}); `ft db migrate` çalıştır."
            )
    else:
        migrate_database(settings)
    return SqliteUnitOfWork(settings.db_path, readonly=readonly)


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


def statement_file() -> StatementFile:
    return CsvStatementFile()


def transaction_file() -> TransactionFile:
    return CsvTransactionFile()


def run_doctor(settings: Settings) -> list[Check]:
    version, supported = sqlite_version()
    checks = [Check("SQLite", "ok" if supported else "fail", version)]
    schema_ok = False
    if not settings.db_path.exists():
        checks.append(
            Check("Veritabanı şeması", "fail", "veritabanı yok; `ft db migrate` çalıştır")
        )
    else:
        status = schema_status(settings.db_path)
        if status.current == status.latest:
            schema_ok = True
            checks.append(Check("Veritabanı şeması", "ok", f"güncel (sürüm {status.current})"))
        elif status.current < status.latest:
            checks.append(
                Check(
                    "Veritabanı şeması",
                    "warn",
                    f"sürüm {status.current}, en son {status.latest}; `ft db migrate` çalıştır",
                )
            )
        else:
            checks.append(
                Check(
                    "Veritabanı şeması",
                    "fail",
                    f"veritabanı sürümü ({status.current}) koddan ({status.latest}) yeni",
                )
            )
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
    checks.append(_env_check(Path(".env")))
    return checks


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


def _evds_key_check(settings: Settings) -> Check:
    if settings.evds_api_key is None:
        return Check("EVDS anahtarı", "warn", "FT_EVDS_API_KEY tanımlı değil")
    return Check("EVDS anahtarı", "ok", "tanımlı")


def _env_check(path: Path) -> Check:
    if not path.exists():
        return Check(".env izinleri", "ok", "dosya yok")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return Check(".env izinleri", "warn", f"{mode:o}; 600 olmalı (chmod 600 .env)")
    return Check(".env izinleri", "ok", f"{mode:o}")
