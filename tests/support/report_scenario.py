"""Rapor snapshot'ları için test veritabanı senaryosu; değerler gerçek akıştan üretilir."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.report import ReportKind, build_report, payday_plan
from finans.contracts.report import PaydayPlan, Report
from finans.domain.models import (
    CpiPoint,
    Instrument,
    InstrumentKind,
    PricePoint,
    Side,
    Transaction,
    YearMonth,
)
from finans.domain.portfolio import AlertThresholds, PortfolioConfig
from finans.ports.repositories import AlertState

D = Decimal
SERIES = "TP.TUKFIY2025.GENEL"
NOW = datetime(2026, 11, 30, 9, 0, tzinfo=UTC)
PRICE_FETCH = datetime(2026, 11, 27, 18, 31, tzinfo=UTC)
CPI_FETCH = datetime(2026, 11, 3, 7, 35, tzinfo=UTC)
XHT = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse")
XPP = Instrument("XPP", InstrumentKind.TEFAS_YAT, "dusuk_risk", category="para_piyasasi")
XAC = Instrument("XAC", InstrumentKind.TEFAS_YAT, "acil_durum", allocation=False)
CONFIG = PortfolioConfig(
    (XHT, XPP, XAC),
    {"hisse": D("0.6"), "dusuk_risk": D("0.4")},
    D(1000),
    AlertThresholds(),
    payday=15,
)
PRICES = {
    date(2026, 11, 2): {"XHT": "10", "XPP": "20", "XAC": "50"},
    date(2026, 11, 20): {"XHT": "10.5", "XPP": "20", "XAC": "50"},
    date(2026, 11, 25): {"XHT": "11", "XPP": "20.1", "XAC": "50.2"},
    date(2026, 11, 27): {"XHT": "11.5", "XPP": "20.2", "XAC": "50.5"},
}
# TEFAS fiyatları 6 basamaklı girilir; daha kısası K-64'te bilgi notu üretirdi.
TRADES = [
    Transaction("XHT", date(2026, 11, 2), Side.BUY, D(100), D("10.000000")),
    Transaction("XPP", date(2026, 11, 2), Side.BUY, D(50), D("20.000000")),
    Transaction("XAC", date(2026, 11, 2), Side.BUY, D(10), D("50.000000")),
    Transaction("XHT", date(2026, 11, 25), Side.BUY, D(10), D("11.000000")),
]


def seed(db: Path, *, priced: tuple[str, ...] = ("XHT", "XPP", "XAC"), alarm: bool = False) -> None:
    """`priced` dışındaki fonlara hiç fiyat yazılmaz; `alarm` sessiz dönemi bitmiş, açık bir
    sapma alarmı kurar."""
    with SqliteUnitOfWork(db) as uow:
        uow.instruments.sync(list(CONFIG.instruments))
        for day, prices in PRICES.items():
            for code, price in prices.items():
                if code in priced:
                    point = PricePoint(code, day, D(price), "tefas")
                    uow.prices.upsert(point, fetched_at=PRICE_FETCH)
        for tx in TRADES:
            uow.transactions.add(tx, external_ref=None, note=None, created_at=NOW)
        for period, index in ((YearMonth(2025, 10), D(100)), (YearMonth(2026, 10), D(130))):
            uow.cpi.upsert(SERIES, CpiPoint(period, index), base="2025=100", fetched_at=CPI_FETCH)
        if alarm:
            uow.allocation_state.end_quiet(date(2026, 11, 20))
            opened = datetime(2026, 11, 21, 18, 35, tzinfo=UTC)
            uow.alerts.save(AlertState("drift:hisse", "below", opened, None, opened, "{}"))


def report(db: Path, kind: ReportKind, on: date) -> Report:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        return build_report(
            uow,
            CONFIG,
            kind=kind,
            logical_date=on,
            contribution=CONFIG.monthly_contribution,
            now=NOW,
            cpi_series=SERIES,
        )


def payday(db: Path, on: date) -> PaydayPlan:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        return payday_plan(uow, CONFIG, on=on, contribution=CONFIG.monthly_contribution)
