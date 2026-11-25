"""`ft web sifre`: stdout'a yalnız özet satırı gider, şifre hiçbir yere yazılmaz (K-126)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.application.password import verify_password, well_formed
from finans.cli.main import app

runner = CliRunner()
PASSWORD = "uzun bir parola cümlesi"  # noqa: S105 - sahte test değeri


def _printed(stdout: str) -> list[str]:
    """CliRunner gizli girişi taklit ederken istem sonunu stdout'a yazar; gerçek getpass
    terminale yazar. Boş satırlar bu yüzden sayılmaz."""
    return [line for line in stdout.splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _no_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Komut ayar ve veritabanı istemez; kurulumda finans.env'den önce çalışabilir."""
    monkeypatch.chdir(tmp_path)
    for name in ("FT_DB_PATH", "CREDENTIALS_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)


def test_only_the_hash_reaches_stdout() -> None:
    result = runner.invoke(app, ["web", "sifre"], input=f"{PASSWORD}\n{PASSWORD}\n")

    assert result.exit_code == 0, result.output
    [stored] = _printed(result.stdout)
    assert well_formed(stored)
    assert verify_password(PASSWORD, stored)
    assert PASSWORD not in result.output


def test_a_short_password_is_refused_with_the_reason_before_confirmation() -> None:
    result = runner.invoke(app, ["web", "sifre"], input="kısa şifre\n")

    assert result.exit_code == 2
    assert _printed(result.stdout) == []
    assert "en az 12 karakter olmalı; 10 verildi" in result.stderr
    assert "Tekrar" not in result.stderr


def test_a_mismatched_confirmation_writes_nothing() -> None:
    result = runner.invoke(app, ["web", "sifre"], input=f"{PASSWORD}\nbaşka bir parola cümlesi\n")

    assert result.exit_code == 2
    assert _printed(result.stdout) == []
    assert "eşleşmedi" in result.stderr
