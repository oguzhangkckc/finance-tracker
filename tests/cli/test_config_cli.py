from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.cli.main import app

runner = CliRunner()
VALID = """
[targets]
hisse = 0.6
altin = 0.4

[[instruments]]
code = "TTE"
kind = "TEFAS_YAT"
asset_class = "hisse"

[[instruments]]
code = "ALTIN_GR"
kind = "MANUAL"
asset_class = "altin"
"""
THIRDS = """
[targets]
hisse = 0.3333
dusuk_risk = 0.3333
altin = 0.3333

[[instruments]]
code = "TTE"
kind = "TEFAS_YAT"
asset_class = "hisse"

[[instruments]]
code = "AFT"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"

[[instruments]]
code = "ALTIN_GR"
kind = "MANUAL"
asset_class = "altin"
"""


@pytest.fixture
def portfolio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "portfolio.toml"
    path.write_text(VALID, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "var" / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(path))
    return path


def test_check_valid_file(portfolio: Path) -> None:
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 0, result.output
    assert "Config geçerli: 2 varlık, 2 hedef sınıf." in result.output


def test_check_lists_every_issue_and_exits_with_one(portfolio: Path) -> None:
    portfolio.write_text(THIRDS, encoding="utf-8")
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 1
    assert "Config'te 1 hata var:" in result.output
    assert "altin değerini 0.3333 yerine 0.3334 yaparsan toplam tam 1 olur" in result.output


def test_apply_writes_instruments_and_reports_changes(portfolio: Path) -> None:
    first = runner.invoke(app, ["config", "apply"])
    assert first.exit_code == 0, first.output
    assert "Eklenen: ALTIN_GR, TTE" in first.output
    assert (
        "Ayarlar: başlangıç sürümü portfolio.toml'dan yazıldı (yürürlük 0001-01-01)."
        in first.output
    )
    second = runner.invoke(app, ["config", "apply"])
    assert second.output == "Değişiklik yok.\n"


def test_apply_refuses_removing_a_class_that_still_has_weight(portfolio: Path) -> None:
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    shares_only = VALID.replace("hisse = 0.6\naltin = 0.4", "hisse = 1").split(
        '[[instruments]]\ncode = "ALTIN_GR"'
    )[0]
    portfolio.write_text(shares_only, encoding="utf-8")

    result = runner.invoke(app, ["config", "apply"])

    assert result.exit_code == 1
    assert "Config'te 1 hata var:" in result.output
    assert "targets.altin: portfolio.toml'dan silinmiş" in result.output
    assert "Önce ağırlığını 0 yap" in result.output
    assert "Pasif yapılan" not in result.output


def test_file_option_overrides_the_environment(portfolio: Path, tmp_path: Path) -> None:
    other = tmp_path / "diger.toml"
    other.write_text(THIRDS.replace("altin = 0.3333", "altin = 0.3334"), encoding="utf-8")
    result = runner.invoke(app, ["config", "check", "--file", str(other)])
    assert result.exit_code == 0, result.output
    assert "3 varlık" in result.output


def test_missing_portfolio_path_exits_with_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 2
    assert "FT_PORTFOLIO_PATH" in result.output
