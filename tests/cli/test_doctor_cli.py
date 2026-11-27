import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.adapters.sqlite.migrate import bundled
from finans.cli.main import app

runner = CliRunner()
PORTFOLIO = """
[targets]
hisse = 1

[[instruments]]
code = "TTE"
kind = "TEFAS_YAT"
asset_class = "hisse"
"""


@pytest.fixture
def portfolio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "portfolio.toml"
    path.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(path))
    return path


def test_healthy_setup(portfolio: Path) -> None:
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    for line in [
        "✓ SQLite: ",
        f"✓ Veritabanı şeması: güncel (sürüm {len(bundled())})",
        "✓ Config: 1 varlık, 1 hedef sınıf",
        "✓ Config ile veritabanı: uyumlu",
        "✓ Pasif varlıkta pay: yok",
        "✓ Ayarlar: başlangıç sürümü (portfolio.toml)",
        "! Fiyatlar: fiyatı yok: TTE; 1 bayatlık uyarısı, ayrıntı için `ft data check`",
        "✓ .env izinleri: dosya yok",
    ]:
        assert line in result.output


def test_missing_database_and_invalid_config_fail(portfolio: Path) -> None:
    portfolio.write_text(PORTFOLIO.replace("hisse = 1", "hisse = 0.9"), encoding="utf-8")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "✗ Veritabanı şeması: veritabanı yok; `ft db migrate` çalıştır" in result.output
    assert "✗ Config: 1 hata; ayrıntı için `ft config check`" in result.output


def test_loose_env_permissions_are_a_warning(portfolio: Path, tmp_path: Path) -> None:
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    env = tmp_path / ".env"
    env.write_text("FT_LOG_LEVEL=INFO\n", encoding="utf-8")
    os.chmod(env, 0o644)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "! .env izinleri: 644; 600 olmalı (chmod 600 .env)" in result.output


def test_age_secret_key_on_the_server_fails_without_showing_it(
    portfolio: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    monkeypatch.setenv("FT_BACKUP_DIR", str(tmp_path / "yedek"))
    monkeypatch.setenv("FT_BACKUP_AGE_RECIPIENTS", "age1mac, age1kurtarma")
    secret = "AGE-SECRET-KEY-1DENEME"  # noqa: S105 - sahte test değeri
    (tmp_path / ".env").write_text(f"# {secret}\n", encoding="utf-8")
    os.chmod(tmp_path / ".env", 0o600)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "✗ age gizli anahtarı: sunucuda bulundu, kaldır: .env" in result.output
    assert secret not in result.output


def test_backup_directory_must_hold_only_encrypted_backups(
    portfolio: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    directory = tmp_path / "yedek"
    directory.mkdir()
    monkeypatch.setenv("FT_BACKUP_DIR", str(directory))
    monkeypatch.setenv("FT_BACKUP_AGE_RECIPIENTS", "age1mac, age1kurtarma")
    for name in ("finans-20261126T001500Z.db.age", "finans-20261126T001500Z.db.age.sha256"):
        (directory / name).write_bytes(b"age-sahte")

    clean = runner.invoke(app, ["doctor"])
    assert "✓ Yedek dizini: yalnız şifreli yedekler ve özetleri" in clean.output

    for stamp in range(10, 17):
        (directory / f"finans-20261125T1344{stamp}Z-v4.db").write_bytes(b"SQLite format 3")
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert (
        "✗ Yedek dizini: beklenmeyen: finans-20261125T134410Z-v4.db, "
        "finans-20261125T134411Z-v4.db, finans-20261125T134412Z-v4.db, "
        "finans-20261125T134413Z-v4.db, finans-20261125T134414Z-v4.db ve 2 tane daha; "
        "Mac bu dizini çeker, yalnız şifreli yedek durmalı."
    ) in result.output


@pytest.mark.parametrize("content", ["\n", "düz metin şifre\n"])
def test_a_leftover_web_password_file_is_not_checked_any_more(
    portfolio: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """K-137: şifre kilidi kalktı; geçiş gününde silinene kadar duran dosya doctor'ı bozmaz."""
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "ft_web_password").write_text(content, encoding="utf-8")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setenv("FT_WEB_ORIGIN", "https://finans.ornek.com")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Web yazma şifresi" not in result.output
    assert "düz metin" not in result.output
