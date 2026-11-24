from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.cli.main import app
from finans.domain.models import PricePoint

runner = CliRunner()
NOW = datetime(2026, 11, 24, 18, 30, tzinfo=UTC)
PORTFOLIO = """
[targets]
hisse_tr = 0.5
dusuk_risk = 0.5

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse_tr"

[[instruments]]
code = "XPP"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"
"""
XHT = {
    date(2026, 11, 17): "1.7",
    date(2026, 11, 18): "1.71",
    date(2026, 11, 19): "1.72",
    date(2026, 11, 20): "1.744322",
    date(2026, 11, 23): "1.73",
    date(2026, 11, 24): "1.715559",
}


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "finans.db"
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(db))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(portfolio))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    with SqliteUnitOfWork(db) as uow:
        for day, price in XHT.items():
            uow.prices.upsert(PricePoint("XHT", day, Decimal(price), "tefas"), fetched_at=NOW)
            uow.prices.upsert(PricePoint("XPP", day, Decimal(7), "tefas"), fetched_at=NOW)
    for args in (
        ["buy", "XHT", "10", "1.700000", "--date", "2026-11-17"],
        ["buy", "XHT", "5", "1.744322", "--date", "2026-11-20"],
        ["buy", "XPP", "100", "7.0000", "--date", "2026-11-18"],
    ):
        assert runner.invoke(app, ["tx", "add", *args]).exit_code == 0


def _statement(tmp_path: Path, rows: str) -> str:
    path = tmp_path / "ekstre.csv"
    path.write_text("date,code,units,price,value\n" + rows, encoding="utf-8")
    return str(path)


def test_matching_statement_passes(tmp_path: Path) -> None:
    path = _statement(tmp_path, "2026-11-23,XHT,15,1.73,25.95\n2026-11-23,XPP,100,,700\n")

    result = runner.invoke(app, ["reconcile", path])

    assert result.exit_code == 0, result.output
    assert "✓ 2026-11-23 XHT (satır 2): uyumlu (değer farkı 0 TL)" in result.output
    assert "ekstre gününün fiyatı: 2 kalem" in result.output
    assert "Mutabakat: geçti (2 kalem, hepsi ±0,01 TL içinde)." in result.output


def test_price_date_difference_and_missing_line_fail_with_evidence(tmp_path: Path) -> None:
    path = _statement(tmp_path, "2026-11-23,XHT,15,1.744322,26.16\n")

    result = runner.invoke(app, ["reconcile", path])

    assert result.exit_code == 1
    assert (
        "✗ 2026-11-23 XHT (satır 2): fiyat farkı: ekstrede 1.744322, kayıtlarda 1.73 "
        "(2026-11-23); ekstre fiyatı 2026-11-20 TEFAS fiyatıyla eşleşiyor (-1 işlem günü); "
        "değer de tutuyor"
    ) in result.output
    assert "✗ 2026-11-23 XPP: kayıtlarda 100 adet var ama ekstrede yok" in result.output
    assert "1 işlem günü önceki fiyat: 1 kalem" in result.output
    assert "    XHT: ekstre 2026-11-23, TEFAS fiyatı 2026-11-20 (fiyat ve değer)" in result.output
    assert "Mutabakat: kaldı (2/2 kalem uyumsuz)." in result.output


def test_units_gap_names_the_recent_trade_by_its_number(tmp_path: Path) -> None:
    path = _statement(tmp_path, "2026-11-23,XHT,10,1.73,17.30\n2026-11-23,XPP,100,,700\n")

    result = runner.invoke(app, ["reconcile", path])

    assert result.exit_code == 1
    assert (
        "✗ 2026-11-23 XHT (satır 2): adet farkı: ekstrede 10, kayıtlarda 15; "
        "olası valör farkı (işlem #2, 2026-11-20)"
    ) in result.output


def test_unreadable_or_empty_statement_is_rejected(tmp_path: Path) -> None:
    bad = runner.invoke(app, ["reconcile", _statement(tmp_path, "2026-11-23,XHT,0,1,1\n")])
    assert bad.exit_code == 1
    assert "satır 2: units: sıfırdan büyük olmalı" in bad.output

    empty = runner.invoke(app, ["reconcile", _statement(tmp_path, "")])
    assert empty.exit_code == 1
    assert "Ekstrede satır yok." in empty.output
