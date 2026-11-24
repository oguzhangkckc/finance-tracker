import hashlib
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from finans.adapters.sqlite.snapshot import SqliteCopier
from finans.application.backup import (
    BackupOutcome,
    create_backup,
    files_with_secret_keys,
    recipient_problems,
    verify_backups,
)
from finans.ports.backup import BackupError, DatabaseCopier

NOW = datetime(2026, 11, 30, 0, 0, tzinfo=UTC)
KEYS = ("age1mac", "age1kurtarma")


@dataclass
class FakeEncryptor:
    fail: bool = False
    seen: list[tuple[int, int, tuple[str, ...]]] = field(default_factory=list)

    def encrypt(self, source: Path, target: Path, recipients: Sequence[str]) -> None:
        modes = (stat.S_IMODE(source.stat().st_mode), stat.S_IMODE(source.parent.stat().st_mode))
        self.seen.append((*modes, tuple(recipients)))
        if self.fail:
            raise BackupError("age şifreleyemedi: deneme hatası")
        target.write_bytes(b"age-sahte:" + source.read_bytes())


class BrokenCopier:
    def copy_to(self, target: Path) -> None:
        target.write_bytes(b"bozuk")

    def integrity_check(self, path: Path) -> str:
        return "*** in database main ***"


def _backup(
    db: Path,
    tmp: Path,
    encryptor: FakeEncryptor,
    *,
    now: datetime = NOW,
    copier: DatabaseCopier | None = None,
    recipients: Sequence[str] = KEYS,
) -> BackupOutcome:
    return create_backup(
        copier=copier or SqliteCopier(db),
        encryptor=encryptor,
        recipients=recipients,
        directory=tmp / "yedek",
        scratch_parent=tmp / "gecici",
        now=now,
    )


def _plaintext_left(tmp: Path) -> list[str]:
    scratch = tmp / "gecici"
    return sorted(path.name for path in scratch.rglob("*")) if scratch.exists() else []


def test_backup_is_encrypted_for_every_recipient_with_a_checksum(
    migrated_db: Path, tmp_path: Path
) -> None:
    encryptor = FakeEncryptor()

    outcome = _backup(migrated_db, tmp_path, encryptor)

    target = tmp_path / "yedek" / "finans-20261130T000000Z.db.age"
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    assert (outcome.name, outcome.integrity, outcome.sha256) == (target.name, "ok", digest)
    assert encryptor.seen == [(0o600, 0o700, KEYS)]
    assert target.read_bytes().startswith(b"age-sahte:SQLite format 3")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    sidecar = tmp_path / "yedek" / f"{target.name}.sha256"
    assert sidecar.read_text(encoding="utf-8") == f"{digest}  {target.name}\n"
    assert _plaintext_left(tmp_path) == []


def test_failed_encryption_leaves_no_plaintext_behind(migrated_db: Path, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="deneme hatası"):
        _backup(migrated_db, tmp_path, FakeEncryptor(fail=True))

    assert _plaintext_left(tmp_path) == []
    assert list((tmp_path / "yedek").iterdir()) == []


def test_failed_integrity_check_stops_before_encryption(migrated_db: Path, tmp_path: Path) -> None:
    encryptor = FakeEncryptor()

    with pytest.raises(BackupError, match="bütünlük denetimi başarısız"):
        _backup(migrated_db, tmp_path, encryptor, copier=BrokenCopier())

    assert encryptor.seen == []
    assert _plaintext_left(tmp_path) == []


def test_only_public_keys_are_accepted(migrated_db: Path, tmp_path: Path) -> None:
    secret = "AGE-SECRET-KEY-1QQQQ"  # noqa: S105 - sahte test değeri

    with pytest.raises(BackupError) as caught:
        _backup(migrated_db, tmp_path, FakeEncryptor(), recipients=("age1mac", secret))

    assert "2. alıcı bir gizli anahtar" in str(caught.value)
    assert secret not in str(caught.value)
    assert recipient_problems([]) == ["alıcı yok; FT_BACKUP_AGE_RECIPIENTS tanımla"]
    assert recipient_problems(["ssh-ed25519 AAAA"]) == [
        "1. alıcı bir age açık anahtarı değil (age1… ile başlamalı)"
    ]


def test_last_fourteen_backups_are_kept(migrated_db: Path, tmp_path: Path) -> None:
    for hour in range(15):
        _backup(migrated_db, tmp_path, FakeEncryptor(), now=NOW + timedelta(hours=hour))

    directory = tmp_path / "yedek"
    names = sorted(path.name for path in directory.glob("*.db.age"))
    assert (len(names), names[0]) == (14, "finans-20261130T010000Z.db.age")
    assert not (directory / "finans-20261130T000000Z.db.age.sha256").exists()


def test_server_side_verification_checks_the_checksums(migrated_db: Path, tmp_path: Path) -> None:
    _backup(migrated_db, tmp_path, FakeEncryptor())
    second = _backup(migrated_db, tmp_path, FakeEncryptor(), now=NOW + timedelta(hours=1))
    directory = tmp_path / "yedek"
    (directory / second.name).write_bytes(b"bozulmus")
    (directory / "finans-20261129T000000Z.db.age").write_bytes(b"x")

    assert [(c.name, c.ok, c.message) for c in verify_backups(directory)] == [
        ("finans-20261129T000000Z.db.age", False, "özet dosyası yok"),
        ("finans-20261130T000000Z.db.age", True, "özet tutuyor"),
        ("finans-20261130T010000Z.db.age", False, "özet tutmuyor; dosya bozulmuş olabilir"),
    ]


def test_secret_keys_are_found_in_files_and_directories(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FT_BACKUP_AGE_RECIPIENTS=age1mac\n", encoding="utf-8")
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "age").write_text("AGE-SECRET-KEY-1ABC\n", encoding="utf-8")

    assert files_with_secret_keys([env, credentials]) == [credentials / "age"]
