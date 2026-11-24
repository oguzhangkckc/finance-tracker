from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans import bootstrap
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.cli.main import app
from finans.domain.models import PricePoint
from tests.fakes.clock import FixedClock

runner = CliRunner()
NOW = datetime(2026, 11, 24, 18, 30, tzinfo=UTC)
PORTFOLIO = """
[targets]
hisse_tr = 0.5
dusuk_risk = 0.5

[quality.jump]
hisse_tr = 0.15

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse_tr"

[[instruments]]
code = "XPP"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"
category = "para_piyasasi"
"""
DAYS = [date(2026, 11, d) for d in (17, 18, 19, 20, 23, 24)]
XHT = ("1.7", "1.71", "1.72", "1.744322", "1.73", "1.715559")


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = tmp_path / "finans.db"
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(db))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(portfolio))
    monkeypatch.setattr(bootstrap, "system_clock", lambda: FixedClock(NOW))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    return db


def _prices(db: Path, bgp: str) -> None:
    with SqliteUnitOfWork(db) as uow:
        for day, aku, mm in zip(DAYS, XHT, bgp, strict=True):
            uow.prices.upsert(PricePoint("XHT", day, Decimal(aku), "tefas"), fetched_at=NOW)
            uow.prices.upsert(PricePoint("XPP", day, Decimal(mm), "tefas"), fetched_at=NOW)


def test_data_check_lists_issues_with_a_summary(configured: Path) -> None:
    _prices(configured, "777776")

    result = runner.invoke(app, ["data", "check", "--since", "2026-11-01"])

    assert result.exit_code == 0, result.output
    assert "! [monotonluk] XPP 2026-11-24: para piyasası fonunun fiyatı düştü: 7 → 6" in (
        result.output
    )
    assert "! [sıçrama] XPP 2026-11-24: günlük değişim %-14.29" in result.output
    assert "2 uyarı, 0 bilgi" in result.output


def test_clean_data_says_so(configured: Path) -> None:
    _prices(configured, "777777")
    result = runner.invoke(app, ["data", "check"])
    assert result.exit_code == 0, result.output
    assert "Veri sorunu yok." in result.output


def test_bad_since_is_rejected() -> None:
    assert runner.invoke(app, ["data", "check", "--since", "2026-13-01"]).exit_code == 2


def test_tx_add_warns_about_a_mismatching_price_but_still_adds(configured: Path) -> None:
    _prices(configured, "777777")

    result = runner.invoke(app, ["tx", "add", "buy", "XHT", "10", "1.7443", "--date", "2026-11-23"])

    assert result.exit_code == 0, result.output
    assert "İşlem eklendi: #1" in result.output
    assert (
        "Uyarı: [işlem fiyatı] XHT 2026-11-23 #1: fiyat 1.7443 o günün TEFAS fiyatıyla (1.73) "
        "uyuşmuyor" in result.output
    )


def test_tx_import_warns_per_line(configured: Path, tmp_path: Path) -> None:
    _prices(configured, "777777")
    csv = tmp_path / "islemler.csv"
    csv.write_text("date,code,side,units,price\n2026-11-21,XHT,BUY,10,1.715559\n", encoding="utf-8")

    result = runner.invoke(app, ["tx", "import", str(csv), "--dry-run"])

    assert result.exit_code == 0, result.output
    expected = "Uyarı: [işlem fiyatı] XHT 2026-11-21 satır 2: işlem gününde TEFAS fiyatı yok"
    assert expected in result.output
