import hashlib
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

from finans.adapters.sqlite.codec import encode_timestamp
from finans.adapters.sqlite.connection import transaction
from finans.ports.clock import Clock

_FILE_NAME = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS _migration (
  version     INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  sha256      TEXT NOT NULL,
  applied_at  TEXT NOT NULL
) STRICT
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    sha256: str


def discover(directory: Traversable) -> list[Migration]:
    found: dict[int, Migration] = {}
    for entry in directory.iterdir():
        if not entry.is_file() or not entry.name.endswith(".sql"):
            continue
        match = _FILE_NAME.match(entry.name)
        if match is None:
            raise MigrationError(f"Geçersiz migration adı: {entry.name} (beklenen: NNNN_ad.sql)")
        version = int(match["version"])
        if version in found:
            raise MigrationError(f"Aynı sürüm iki kez: {found[version].name}, {entry.name}")
        raw = entry.read_bytes()
        found[version] = Migration(
            version=version,
            name=entry.name,
            sql=raw.decode("utf-8"),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    migrations = [found[v] for v in sorted(found)]
    _require_contiguous(migrations)
    return migrations


def bundled() -> list[Migration]:
    return discover(files("finans.adapters.sqlite.migrations"))


def apply(conn: sqlite3.Connection, migrations: Sequence[Migration], *, clock: Clock) -> list[int]:
    _require_contiguous(migrations)
    latest = len(migrations)
    applied: list[int] = []
    with transaction(conn):
        conn.execute(_LEDGER_DDL)
        current = _user_version(conn)
        if current > latest:
            raise MigrationError(
                f"Veritabanı sürümü ({current}), kodun bildiği en yüksek sürümden ({latest}) "
                "yeni; bu veritabanı eski kodla açılmaz"
            )
        _verify_applied(conn, migrations[:current])
        for migration in migrations[current:]:
            _apply_one(conn, migration, clock)
            applied.append(migration.version)
    return applied


def _apply_one(conn: sqlite3.Connection, migration: Migration, clock: Clock) -> None:
    try:
        conn.executescript(migration.sql)
    except sqlite3.Error as exc:
        raise MigrationError(f"{migration.name} uygulanamadı: {exc}") from exc
    if not conn.in_transaction:
        raise MigrationError(
            f"{migration.name} transaction'ı kendisi kapattı; "
            "migration dosyaları BEGIN/COMMIT içermemeli"
        )
    conn.execute(
        "INSERT INTO _migration (version, name, sha256, applied_at) VALUES (?, ?, ?, ?)",
        (migration.version, migration.name, migration.sha256, encode_timestamp(clock.now())),
    )
    conn.execute(f"PRAGMA user_version = {migration.version:d}")


def _verify_applied(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> None:
    recorded: dict[int, str] = dict(conn.execute("SELECT version, sha256 FROM _migration"))
    for migration in migrations:
        checksum = recorded.get(migration.version)
        if checksum is None:
            raise MigrationError(
                f"{migration.name} uygulanmış görünüyor (user_version) ama _migration kaydı yok"
            )
        if checksum != migration.sha256:
            raise MigrationError(
                f"{migration.name} uygulandıktan sonra değiştirilmiş (sha256 uyuşmuyor); "
                "uygulanmış migration değiştirilmez, düzeltme için yeni migration yaz"
            )


def _require_contiguous(migrations: Sequence[Migration]) -> None:
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"Migration sürümleri 1'den başlayıp boşluksuz artmalı: {versions}")


def _user_version(conn: sqlite3.Connection) -> int:
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    return int(version)
