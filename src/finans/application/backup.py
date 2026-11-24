"""Gece yedeği (K-82): kopya, bütünlük denetimi, age ile şifreleme, özet ve eski kopyaların
silinmesi. Sunucu yedeği çözemez; tam geri yükleme testi Mac'te yapılır."""

import hashlib
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from finans.ports.backup import BackupError, DatabaseCopier, Encryptor

KEEP: Final = 14
SECRET_MARK: Final = "AGE-SECRET-KEY-"  # noqa: S105 - aranacak önek, sır değil
_PREFIX: Final = "finans-"
_SUFFIX: Final = ".db.age"
_CHUNK: Final = 1 << 20


@dataclass(frozen=True, slots=True)
class BackupOutcome:
    name: str
    sha256: str
    size: int
    integrity: str
    removed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackupCheck:
    name: str
    ok: bool
    message: str


def recipient_problems(recipients: Sequence[str]) -> list[str]:
    """Boş liste geçerli demektir; değerler mesaja yazılmaz."""
    if not recipients:
        return ["alıcı yok; FT_BACKUP_AGE_RECIPIENTS tanımla"]
    problems = []
    for number, recipient in enumerate(recipients, 1):
        if recipient.upper().startswith(SECRET_MARK):
            problems.append(
                f"{number}. alıcı bir gizli anahtar; sunucuda yalnızca açık anahtar (age1…) durur"
            )
        elif not recipient.startswith("age1"):
            problems.append(f"{number}. alıcı bir age açık anahtarı değil (age1… ile başlamalı)")
    return problems


def create_backup(
    *,
    copier: DatabaseCopier,
    encryptor: Encryptor,
    recipients: Sequence[str],
    directory: Path,
    scratch_parent: Path,
    now: datetime,
    keep: int = KEEP,
) -> BackupOutcome:
    """Şifresiz kopya 700 izinli geçici dizinde 600 izinle oluşur ve her durumda silinir."""
    problems = recipient_problems(recipients)
    if problems:
        raise BackupError("; ".join(problems))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    scratch_parent.mkdir(parents=True, exist_ok=True)
    name = f"{_PREFIX}{now.astimezone(UTC):%Y%m%dT%H%M%SZ}{_SUFFIX}"
    target = directory / name
    if target.exists():
        raise BackupError(f"{name} zaten var; yedeğin üzerine yazılmaz")
    partial = directory / f".{name}.partial"
    scratch = Path(tempfile.mkdtemp(prefix=".finans-yedek-", dir=scratch_parent))
    try:
        plain = scratch / "finans.db"
        copier.copy_to(plain)
        plain.chmod(0o600)
        integrity = copier.integrity_check(plain)
        if integrity != "ok":
            raise BackupError(f"kopyanın bütünlük denetimi başarısız: {integrity}")
        encryptor.encrypt(plain, partial, recipients)
        partial.chmod(0o600)
        digest = _sha256(partial)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
        _remove_plain(scratch)
    sidecar = directory / f"{name}.sha256"
    sidecar.write_text(f"{digest}  {name}\n", encoding="utf-8")
    sidecar.chmod(0o600)
    return BackupOutcome(name, digest, target.stat().st_size, integrity, _prune(directory, keep))


def verify_backups(directory: Path) -> list[BackupCheck]:
    """Sunucudaki şifreli kopyaların özetini denetler; içerik ancak Mac'te çözülerek denetlenir."""
    checks = []
    for path in sorted(directory.glob(f"{_PREFIX}*{_SUFFIX}")):
        sidecar = path.with_name(f"{path.name}.sha256")
        if not sidecar.exists():
            checks.append(BackupCheck(path.name, False, "özet dosyası yok"))
            continue
        expected = sidecar.read_text(encoding="utf-8").split()[0]
        ok = _sha256(path) == expected
        message = "özet tutuyor" if ok else "özet tutmuyor; dosya bozulmuş olabilir"
        checks.append(BackupCheck(path.name, ok, message))
    return checks


def files_with_secret_keys(paths: Sequence[Path]) -> list[Path]:
    """age gizli anahtarı sunucuda durmaz (K-82); verilen dosya ve dizinlerde arar."""
    found = []
    for path in paths:
        candidates = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file() and SECRET_MARK.encode() in candidate.read_bytes():
                found.append(candidate)
    return found


def _remove_plain(scratch: Path) -> None:
    try:
        shutil.rmtree(scratch)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BackupError(f"şifresiz geçici kopya silinemedi: {scratch}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _prune(directory: Path, keep: int) -> tuple[str, ...]:
    backups = sorted(directory.glob(f"{_PREFIX}*{_SUFFIX}"))
    removed = backups[: max(0, len(backups) - keep)]
    for path in removed:
        path.unlink()
        path.with_name(f"{path.name}.sha256").unlink(missing_ok=True)
    return tuple(path.name for path in removed)
