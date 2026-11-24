from pathlib import Path

import pytest
from typer.testing import CliRunner

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


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(portfolio))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0


def test_add_list_void_flow() -> None:
    added = runner.invoke(
        app, ["tx", "add", "buy", "TTE", "10", "12.5", "--date", "2026-01-05", "--ref", "R1"]
    )
    assert added.exit_code == 0, added.output
    assert "İşlem eklendi: #1" in added.output

    listed = runner.invoke(app, ["tx", "list"])
    assert "#1  2026-01-05  TTE  BUY  10 × 12.5  komisyon 0  ref R1" in listed.output

    voided = runner.invoke(app, ["tx", "void", "1", "--reason", "yanlış tarih"])
    assert voided.exit_code == 0, voided.output
    assert "İşlem #1 iptal edildi." in voided.output
    assert "Kayıtlı işlem yok." in runner.invoke(app, ["tx", "list"]).output
    assert "[İPTAL: yanlış tarih]" in runner.invoke(app, ["tx", "list", "--all"]).output


def test_add_rejects_decimal_comma_and_domain_errors() -> None:
    comma = runner.invoke(app, ["tx", "add", "buy", "TTE", "12,5", "1", "--date", "2026-01-05"])
    assert comma.exit_code == 2
    assert "12.5" in comma.output
    oversell = runner.invoke(app, ["tx", "add", "sell", "TTE", "1", "1", "--date", "2026-01-05"])
    assert oversell.exit_code == 1
    assert "Hata:" in oversell.output


def test_import_reports_and_exits_with_one_on_problems(tmp_path: Path) -> None:
    good = tmp_path / "iyi.csv"
    good.write_text("date,code,side,units,price\n2026-01-05,TTE,BUY,10,12.5\n", encoding="utf-8")
    preview = runner.invoke(app, ["tx", "import", str(good), "--dry-run"])
    assert "Eklenecek: 1, atlanacak (zaten var): 0" in preview.output
    imported = runner.invoke(app, ["tx", "import", str(good)])
    assert imported.exit_code == 0, imported.output
    assert "Eklendi: 1, atlandı (zaten var): 0" in imported.output

    bad = tmp_path / "kotu.csv"
    bad.write_text("date,code,side,units,price\n2026-01-05,TTE,AL,1,1\n", encoding="utf-8")
    failed = runner.invoke(app, ["tx", "import", str(bad)])
    assert failed.exit_code == 1
    assert "İçe aktarma durduruldu; hiçbir işlem yazılmadı. 1 sorun:" in failed.output
    assert "satır 2: side: BUY ya da SELL olmalı" in failed.output
