import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.adapters.sqlite.migrate import bundled
from finans.application.password import hash_password
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


WEB_HASH = hash_password("uzun bir parola cümlesi")


@pytest.mark.parametrize(
    ("content", "line", "code"),
    [
        (None, "✗ Web yazma şifresi: credstore'da yok; finans-web başlamaz", 1),
        ("\n", "! Web yazma şifresi: dosya boş; web'de yazma kapalı", 0),
        (f"{WEB_HASH}\n", "✓ Web yazma şifresi: geçerli scrypt özeti", 0),
        ("düz metin şifre\n", "✗ Web yazma şifresi: scrypt özeti değil; finans-web başlamaz", 1),
    ],
)
def test_the_web_password_file_is_checked_without_showing_it(
    portfolio: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
    line: str,
    code: int,
) -> None:
    """K-126: sorun finans-web yeniden başlamadan görünsün; değer hiçbir durumda yazılmaz."""
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    if content is not None:
        (credentials / "ft_web_password").write_text(content, encoding="utf-8")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setenv("FT_WEB_ORIGIN", "https://cihaz.ornek.ts.net")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == code, result.output
    assert line in result.output
    assert WEB_HASH.split("$")[-1] not in result.output
    assert "düz metin" not in result.output


@pytest.mark.parametrize("credentials", [False, True])
def test_without_a_configured_web_there_is_no_web_password_line(
    portfolio: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, credentials: bool
) -> None:
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    if credentials:
        (tmp_path / "credentials").mkdir()
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path / "credentials"))
    else:
        monkeypatch.setenv("FT_WEB_ORIGIN", "https://cihaz.ornek.ts.net")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Web yazma şifresi" not in result.output
