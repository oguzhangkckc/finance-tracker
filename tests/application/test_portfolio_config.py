from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.portfolio_config import apply_portfolio
from finans.domain.models import Instrument, InstrumentKind, Side, Transaction
from finans.domain.portfolio import AlertThresholds, PortfolioConfig

D = Decimal
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")
CONFIG = PortfolioConfig(
    instruments=(TTE, ALTIN),
    targets={"hisse": D("0.6"), "altin": D("0.4")},
    monthly_contribution=D(0),
    alerts=AlertThresholds(),
)
NOW = datetime(2026, 11, 24, tzinfo=UTC)


def test_apply_reports_changes_and_warns_when_a_held_instrument_is_deactivated(
    migrated_db: Path,
) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        report = apply_portfolio(uow, CONFIG)
        assert report.sync.added == ("ALTIN_GR", "TTE")
        assert report.warnings == ()
        uow.transactions.add(
            Transaction("TTE", date(2026, 1, 5), Side.BUY, D("12.5"), D(10)),
            external_ref=None,
            note=None,
            created_at=NOW,
        )

    gold_only = replace(CONFIG, instruments=(ALTIN,), targets={"altin": D(1)})
    with SqliteUnitOfWork(migrated_db) as uow:
        report = apply_portfolio(uow, gold_only)

    assert report.sync.deactivated == ("TTE",)
    assert report.warnings == (
        "TTE pasif yapıldı ama elde 12.5 adet var; satış girilebilir, alış girilemez.",
    )


def test_deactivating_an_instrument_without_holdings_gives_no_warning(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        apply_portfolio(uow, CONFIG)
        report = apply_portfolio(uow, replace(CONFIG, instruments=(ALTIN,)))
    assert report.sync.deactivated == ("TTE",)
    assert report.warnings == ()
