import sqlite3
from contextlib import closing
from pathlib import Path

from finans.adapters.sqlite.backup import write_backup
from finans.adapters.sqlite.connection import connect


class SqliteCopier:
    """Gece yedeği için kaynak kopya (K-82); migration öncesi yedekle aynı yazıcı (K-55)."""

    def __init__(self, database: Path, *, sanal: bool = False) -> None:
        self._database = database
        self._sanal = sanal

    def copy_to(self, target: Path) -> None:
        with closing(connect(self._database, sanal=self._sanal)) as source:
            write_backup(source, target)

    def integrity_check(self, path: Path) -> str:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as copy:
            rows = copy.execute("PRAGMA integrity_check").fetchall()
        return "; ".join(str(row[0]) for row in rows)
