import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.cli.main import app
from finans.domain.models import PricePoint, Side, Transaction

runner = CliRunner()
D = Decimal
NOW = datetime(2026, 11, 30, 9, 0, tzinfo=UTC)
PORTFOLIO = """
[contribution]
monthly = 1000
payday = 15

[targets]
hisse = 0.6
dusuk_risk = 0.4

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse"

[[instruments]]
code = "XPP"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"

[[instruments]]
code = "XAC"
kind = "TEFAS_YAT"
asset_class = "acil_durum"
allocation = false
"""


@pytest.fixture
def portfolio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "finans.db"
    path = tmp_path / "portfolio.toml"
    path.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(db))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(path))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    with SqliteUnitOfWork(db) as uow:
        for code, price in (("XHT", "11.5"), ("XPP", "20.2"), ("XAC", "50.5")):
            uow.prices.upsert(
                PricePoint(code, date(2026, 11, 27), D(price), "tefas"), fetched_at=NOW
            )
        for code, units, cost in (("XHT", 110, 10), ("XPP", 50, 20), ("XAC", 10, 50)):
            uow.transactions.add(
                Transaction(code, date(2026, 11, 2), Side.BUY, D(units), D(cost)),
                external_ref=None,
                note=None,
                created_at=NOW,
            )
    return path


@pytest.mark.usefixtures("portfolio")
def test_weekly_report_shows_amounts_locally_and_hides_them_on_request() -> None:
    shown = runner.invoke(app, ["report", "weekly", "--on", "2026-11-29"])
    assert shown.exit_code == 0, shown.output
    assert "Toplam değer: 2.780,00 TL (dağılım içi 2.275,00 TL, dağılım dışı 505,00 TL)" in (
        shown.output
    )

    hidden = runner.invoke(app, ["report", "weekly", "--on", "2026-11-29", "--hide-amounts"])
    assert hidden.exit_code == 0, hidden.output
    assert "TL" not in hidden.output


@pytest.mark.usefixtures("portfolio")
def test_monthly_report_as_json_and_with_a_contribution_override() -> None:
    result = runner.invoke(app, ["report", "monthly", "--on", "2026-11-30", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output, parse_float=Decimal)
    assert (data["kind"], data["rebalance"]["contribution"]) == ("monthly", "1000")

    zero = runner.invoke(app, ["report", "monthly", "--on", "2026-11-30", "--contribution", "0"])
    assert "Bu ay katkı 0." in zero.output


@pytest.mark.usefixtures("portfolio")
def test_payday_plan_with_and_without_amounts() -> None:
    shown = runner.invoke(app, ["report", "payday", "--on", "2026-11-29"])
    assert shown.exit_code == 0, shown.output
    assert "hisse XHT: 700,00 TL (%70,0)" in shown.output

    hidden = runner.invoke(app, ["report", "payday", "--on", "2026-11-29", "--hide-amounts"])
    assert "hisse XHT: katkının %70,0" in hidden.output
    assert "TL" not in hidden.output


def test_payday_needs_a_contribution(portfolio: Path) -> None:
    portfolio.write_text(PORTFOLIO.replace("monthly = 1000\npayday = 15\n", ""), encoding="utf-8")
    result = runner.invoke(app, ["report", "payday", "--on", "2026-11-29"])
    assert result.exit_code == 1
    assert "Katkı tanımlı değil" in result.output
