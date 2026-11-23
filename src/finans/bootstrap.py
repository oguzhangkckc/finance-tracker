from contextlib import closing
from pathlib import Path

from finans.adapters.clock import SystemClock
from finans.adapters.csv_transactions import CsvTransactionFile
from finans.adapters.portfolio_toml import TomlPortfolioSource
from finans.adapters.sqlite.connection import connect, sqlite_version
from finans.adapters.sqlite.migrate import MigrationError, apply, bundled, schema_status
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.doctor import Check, inactive_holdings_check, portfolio_checks
from finans.domain.portfolio import ConfigError, PortfolioConfig
from finans.ports.clock import Clock
from finans.ports.sources import PortfolioConfigSource, TransactionFile
from finans.ports.unit_of_work import UnitOfWork
from finans.settings import Settings

__all__ = [
    "MigrationError",
    "SetupError",
    "migrate_database",
    "open_unit_of_work",
    "portfolio_source",
    "run_doctor",
    "system_clock",
    "transaction_file",
]


class SetupError(Exception):
    pass


def migrate_database(settings: Settings, clock: Clock | None = None) -> list[int]:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(settings.db_path)) as conn:
        return apply(conn, bundled(), clock=clock or SystemClock())


def open_unit_of_work(settings: Settings, *, readonly: bool = False) -> UnitOfWork:
    if readonly:
        if not settings.db_path.exists():
            raise SetupError(
                f"Veritabanı bulunamadı ({settings.db_path}); önce `ft db migrate` çalıştır."
            )
    else:
        migrate_database(settings)
    return SqliteUnitOfWork(settings.db_path, readonly=readonly)


def portfolio_source() -> PortfolioConfigSource:
    return TomlPortfolioSource()


def system_clock() -> Clock:
    return SystemClock()


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


def _env_check(path: Path) -> Check:
    if not path.exists():
        return Check(".env izinleri", "ok", "dosya yok")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return Check(".env izinleri", "warn", f"{mode:o}; 600 olmalı (chmod 600 .env)")
    return Check(".env izinleri", "ok", f"{mode:o}")
