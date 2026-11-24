from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.report import build_report, payday_plan
from finans.contracts.report import (
    AllocationLine,
    PaydayLine,
    RebalanceLine,
    RebalancePlan,
    SystemHealth,
    ValueSplit,
)
from finans.domain.models import (
    CashFlow,
    CpiPoint,
    DomainError,
    Instrument,
    InstrumentKind,
    PricePoint,
    Side,
    Transaction,
    YearMonth,
)
from finans.domain.portfolio import AlertThresholds, PortfolioConfig
from finans.domain.returns import net_present_value
from finans.ports.repositories import AlertState
from tests.support.decimals import is_close

D = Decimal
NOW = datetime(2026, 11, 30, 9, 0, tzinfo=UTC)
SUNDAY = date(2026, 11, 29)
SERIES = "TP.TUKFIY2025.GENEL"
MONTH_END = date(2026, 11, 30)
XHT = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse")
XPP = Instrument("XPP", InstrumentKind.TEFAS_YAT, "dusuk_risk", category="para_piyasasi")
XAC = Instrument("XAC", InstrumentKind.TEFAS_YAT, "acil_durum", allocation=False)
TARGETS = {"hisse": D("0.6"), "dusuk_risk": D("0.4")}
CONFIG = PortfolioConfig((XHT, XPP, XAC), TARGETS, D(1000), AlertThresholds(), payday=15)
PRICES = {
    "XHT": {date(2026, 11, 20): "10.5", date(2026, 11, 27): "11.5"},
    "XPP": {date(2026, 11, 20): "20", date(2026, 11, 27): "20.2"},
    "XAC": {date(2026, 11, 20): "50", date(2026, 11, 27): "50.5"},
}
TRADES = [
    Transaction("XHT", date(2026, 11, 2), Side.BUY, D(100), D(10)),
    Transaction("XPP", date(2026, 11, 2), Side.BUY, D(50), D(20)),
    Transaction("XAC", date(2026, 11, 2), Side.BUY, D(10), D(50)),
    Transaction("XHT", date(2026, 11, 25), Side.BUY, D(10), D(11)),
]


@pytest.fixture
def db(migrated_db: Path) -> Path:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.instruments.sync([XHT, XPP, XAC])
        for code, series in PRICES.items():
            for day, price in series.items():
                uow.prices.upsert(PricePoint(code, day, D(price), "tefas"), fetched_at=NOW)
        for tx in TRADES:
            uow.transactions.add(tx, external_ref=None, note=None, created_at=NOW)
        for period, index in ((YearMonth(2025, 10), D(100)), (YearMonth(2026, 10), D(130))):
            uow.cpi.upsert(SERIES, CpiPoint(period, index), base="2025=100", fetched_at=NOW)
    return migrated_db


def test_weekly_report_splits_values_and_leaves_flows_out_of_the_change(db: Path) -> None:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        report = build_report(
            uow,
            CONFIG,
            kind="weekly",
            logical_date=SUNDAY,
            contribution=D(1000),
            now=NOW,
            cpi_series=SERIES,
        )

    assert report.summary.values == ValueSplit(
        in_allocation=D(2275), out_of_allocation=D("505"), total=D(2780)
    )
    assert report.summary.previous_total == D(2550)
    assert report.summary.change_since == date(2026, 11, 22)
    # Modified Dietz (K-94): 2026-11-25 alımı dönemin 4/7'sinde portföyde.
    assert report.summary.change is not None
    assert is_close(report.summary.change, D(120) / (D(2550) + D(110) * D(4) / D(7)))
    assert report.summary.simple_return == D(2780) / D(2610) - 1
    assert report.summary.money_weighted is None
    assert report.allocation == [
        AllocationLine(
            asset_class="dusuk_risk",
            value=D(1010),
            weight=D(1010) / D(2275),
            target=D("0.4"),
            deviation=D(1010) / D(2275) - D("0.4"),
        ),
        AllocationLine(
            asset_class="hisse",
            value=D(1265),
            weight=D(1265) / D(2275),
            target=D("0.6"),
            deviation=D(1265) / D(2275) - D("0.6"),
        ),
    ]
    assert [(h.instrument, h.allocation, h.value, h.price_date) for h in report.holdings] == [
        ("XAC", False, D("505"), date(2026, 11, 27)),
        ("XHT", True, D(1265), date(2026, 11, 27)),
        ("XPP", True, D(1010), date(2026, 11, 27)),
    ]
    assert report.quiet_period
    assert report.rebalance is None
    assert report.lots == []
    assert report.inflation is None
    assert report.provenance.generated_at == NOW
    assert report.health == SystemHealth(last_price_sync=NOW, last_cpi_sync=NOW, failed_jobs_7d=0)
    assert "işlem fiyatı" in {issue.check for issue in report.data_issues}


def test_monthly_report_adds_returns_lots_inflation_and_the_contribution_plan(db: Path) -> None:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        report = build_report(
            uow,
            CONFIG,
            kind="monthly",
            logical_date=MONTH_END,
            contribution=D(1000),
            now=NOW,
            cpi_series=SERIES,
        )

    money_weighted = report.summary.money_weighted
    assert money_weighted is not None
    assert (money_weighted.status, money_weighted.annualized) == ("ok", False)
    assert money_weighted.rate is not None
    flows = [
        CashFlow(date(2026, 11, 2), D(-2000)),
        CashFlow(date(2026, 11, 25), D(-110)),
        CashFlow(MONTH_END, D(2275)),
    ]
    assert is_close(net_present_value(flows, money_weighted.rate, day_count=28), D(0))
    assert report.summary.real_money_weighted == money_weighted
    assert report.summary.real_same_as_nominal
    assert (report.summary.change_since, report.summary.change) == (date(2026, 10, 31), None)

    assert [(lot.instrument, lot.real_return, lot.cpi_period) for lot in report.lots] == [
        ("XAC", D("0.01"), "2026-10"),
        ("XHT", D("0.15"), "2026-10"),
        ("XHT", D(115) / D(110) - 1, "2026-10"),
        ("XPP", D("0.01"), "2026-10"),
    ]
    holdings = {h.instrument: h for h in report.holdings}
    assert holdings["XAC"].real_return == D("0.01")
    assert holdings["XHT"].real_return is None
    assert report.inflation is not None
    assert (report.inflation.valuation_period, report.inflation.annual_inflation) == (
        "2026-10",
        D("0.3"),
    )
    assert report.rebalance == RebalancePlan(
        contribution=D(1000),
        lines=[
            RebalanceLine(asset_class="dusuk_risk", instrument="XPP", amount=D("300.00")),
            RebalanceLine(asset_class="hisse", instrument="XHT", amount=D("700.00")),
        ],
    )


@pytest.mark.parametrize(
    ("contribution", "expected"),
    [(None, None), (D(0), RebalancePlan(contribution=D(0), lines=[]))],
    ids=["tanimsiz", "sifir"],
)
def test_undefined_and_zero_contributions_produce_no_plan_lines(
    db: Path, contribution: Decimal | None, expected: RebalancePlan | None
) -> None:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        report = build_report(
            uow,
            CONFIG,
            kind="monthly",
            logical_date=MONTH_END,
            contribution=contribution,
            now=NOW,
            cpi_series=SERIES,
        )
    assert report.rebalance == expected


def test_open_alerts_and_finished_quiet_period_are_reported(db: Path) -> None:
    with SqliteUnitOfWork(db) as uow:
        uow.alerts.save(AlertState("drift:hisse", "below", NOW, None, None, "{}"))
        uow.allocation_state.end_quiet(date(2026, 11, 20))
        run = uow.runs.start("sync-prices", date(2026, 11, 27), at=NOW)
        uow.runs.finish(run, "ok", "{}", at=NOW)
        failed = uow.runs.start("backup", date(2026, 11, 28), at=NOW)
        uow.runs.finish(failed, "failed", "{}", at=NOW)
    with SqliteUnitOfWork(db, readonly=True) as uow:
        report = build_report(
            uow,
            CONFIG,
            kind="weekly",
            logical_date=SUNDAY,
            contribution=D(1000),
            now=NOW,
            cpi_series=SERIES,
        )

    assert not report.quiet_period
    [alert] = report.alerts
    assert (alert.asset_class, alert.direction) == ("hisse", "below")
    assert alert.deviation == D(1265) / D(2275) - D("0.6")
    assert report.health == SystemHealth(last_price_sync=NOW, last_cpi_sync=NOW, failed_jobs_7d=1)


def test_payday_plan_splits_the_contribution_and_states_each_share(db: Path) -> None:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        plan = payday_plan(uow, CONFIG, on=SUNDAY, contribution=D(1000))

    assert plan.contribution == D(1000)
    assert plan.lines == [
        PaydayLine(asset_class="dusuk_risk", instrument="XPP", amount=D("300.00"), share=D("0.3")),
        PaydayLine(asset_class="hisse", instrument="XHT", amount=D("700.00"), share=D("0.7")),
    ]


def test_payday_plan_needs_a_contribution(db: Path) -> None:
    with (
        SqliteUnitOfWork(db, readonly=True) as uow,
        pytest.raises(DomainError, match="Katkı tanımlı değil"),
    ):
        payday_plan(uow, CONFIG, on=SUNDAY, contribution=None)
