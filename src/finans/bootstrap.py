from contextlib import closing

from finans.adapters.clock import SystemClock
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import MigrationError, apply, bundled
from finans.ports.clock import Clock
from finans.settings import Settings

__all__ = ["MigrationError", "migrate_database"]


def migrate_database(settings: Settings, clock: Clock | None = None) -> list[int]:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(settings.db_path)) as conn:
        return apply(conn, bundled(), clock=clock or SystemClock())
