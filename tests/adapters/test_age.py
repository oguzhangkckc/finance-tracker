import sys
from pathlib import Path

import pytest

from finans.adapters.age import AgeEncryptor
from finans.ports.backup import BackupError


def _fake_age(tmp_path: Path, *, fail: bool = False) -> Path:
    """Gerçek age yerine argümanlarını çıktı dosyasına yazan küçük program."""
    script = tmp_path / "age"
    body = (
        "import sys\nargs = sys.argv[1:]\n"
        + ("print('age: hata: alıcı geçersiz', file=sys.stderr)\nsys.exit(1)\n" if fail else "")
        + "open(args[args.index('-o') + 1], 'w').write(' '.join(args))\n"
    )
    script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    script.chmod(0o755)
    return script


def test_every_recipient_gets_its_own_flag(tmp_path: Path) -> None:
    source, target = tmp_path / "finans.db", tmp_path / "finans.db.age"
    source.write_bytes(b"x")

    AgeEncryptor(str(_fake_age(tmp_path))).encrypt(source, target, ["age1mac", "age1kurtarma"])

    assert target.read_text(encoding="utf-8") == f"-r age1mac -r age1kurtarma -o {target} {source}"


def test_age_problems_are_reported(tmp_path: Path) -> None:
    source, target = tmp_path / "finans.db", tmp_path / "finans.db.age"

    with pytest.raises(BackupError, match="age şifreleyemedi: age: hata: alıcı geçersiz"):
        AgeEncryptor(str(_fake_age(tmp_path, fail=True))).encrypt(source, target, ["age1x"])
    with pytest.raises(BackupError, match="bulunamadı; age paketini kur"):
        AgeEncryptor(str(tmp_path / "yok")).encrypt(source, target, ["age1x"])
    with pytest.raises(BackupError, match="alıcısı tanımlı değil"):
        AgeEncryptor().encrypt(source, target, [])
