import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

_STAMP = "%Y%m%dT%H%M%SZ"
# Daha yeni bir .partial, aynı anda yedek alan başka bir sürecin olabilir.
STALE_PARTIAL_AGE = timedelta(hours=1)


def backup_name(database: Path, *, version: int, at: datetime) -> str:
    return f"{database.stem}-{at.astimezone(UTC).strftime(_STAMP)}-v{version:d}{database.suffix}"


def write_backup(source: sqlite3.Connection, target: Path) -> None:
    """source'un tutarlı kopyasını tek dosya olarak target'a yazar; var olan dosyaya dokunmaz."""
    if target.exists():
        raise FileExistsError(f"{target} zaten var; yedeğin üzerine yazılmaz")
    # mkstemp dosyayı 600 izinle açar; SQLite var olan dosyanın iznini korur.
    handle, partial_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".partial"
    )
    os.close(handle)
    partial = Path(partial_name)
    try:
        with closing(sqlite3.connect(partial)) as copy:
            source.backup(copy)
            # Backup kaynağın WAL kipini de taşır; DELETE kipinde yedek tek dosya kalır.
            (mode,) = copy.execute("PRAGMA journal_mode = DELETE").fetchone()
            if mode != "delete":
                raise sqlite3.OperationalError(f"yedeğin journal kipi değiştirilemedi ({mode})")
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def prune_backups(directory: Path, database: Path, *, keep: int) -> list[Path]:
    if keep < 1:
        raise ValueError("en az bir yedek tutulmalı")
    pattern = re.compile(_backup_pattern(database))
    # Zaman damgası sabit genişlikte ve addaki ilk değişken alan; ada göre sıra zaman sırasıdır.
    found = sorted(
        path for path in directory.iterdir() if path.is_file() and pattern.fullmatch(path.name)
    )
    removed = found[:-keep]
    for path in removed:
        path.unlink()
    return removed


def remove_stale_partials(directory: Path, database: Path, *, now: datetime) -> list[Path]:
    pattern = re.compile(rf"\.{_backup_pattern(database)}\.[a-z0-9_]+\.partial(-journal)?")
    cutoff = (now - STALE_PARTIAL_AGE).timestamp()
    stale = [
        path
        for path in directory.iterdir()
        if path.is_file() and pattern.fullmatch(path.name) and path.stat().st_mtime < cutoff
    ]
    for path in stale:
        path.unlink(missing_ok=True)
    return stale


def _backup_pattern(database: Path) -> str:
    return rf"{re.escape(database.stem)}-\d{{8}}T\d{{6}}Z-v\d+{re.escape(database.suffix)}"
