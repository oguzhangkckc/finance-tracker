from contextlib import closing

from finans.adapters.clock import SystemClock
from finans.adapters.portfolio_toml import TomlPortfolioSource
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import MigrationError, apply, bundled
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.ports.clock import Clock
from finans.ports.sources import PortfolioConfigSource
from finans.ports.unit_of_work import UnitOfWork
from finans.settings import Settings

__all__ = [
    "MigrationError",
    "SetupError",
    "migrate_database",
    "open_unit_of_work",
    "portfolio_source",
    "system_clock",
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
