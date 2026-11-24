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
