from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.doctor import Check, cpi_check, portfolio_checks, price_check
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

D = Decimal
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")
XHT = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse")


def _config(*instruments: Instrument) -> PortfolioConfig:
    return PortfolioConfig(instruments, {"hisse": D(1)}, D(0), AlertThresholds())


def test_in_sync_and_no_inactive_holdings(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.instruments.sync([TTE, ALTIN])
        assert portfolio_checks(uow, _config(TTE, ALTIN)) == [
            Check("Config ile veritabanı", "ok", "uyumlu"),
            Check("Pasif varlıkta pay", "ok", "yok"),
        ]


def test_differences_and_inactive_holdings_are_warnings(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.instruments.sync([TTE, ALTIN])
        uow.transactions.add(
            Transaction("TTE", date(2026, 1, 5), Side.BUY, D("2.5"), D(10)),
            external_ref=None,
            note=None,
            created_at=datetime(2026, 1, 5, tzinfo=UTC),
        )
        uow.instruments.sync([ALTIN])
        renamed = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin", name="Gram altın")
        bitcoin = Instrument("BTC", InstrumentKind.MANUAL, "kripto")
        assert portfolio_checks(uow, _config(renamed, bitcoin)) == [
            Check(
                "Config ile veritabanı",
                "warn",
                "`ft config apply` gerekli; eklenecek: BTC; farklı: ALTIN_GR",
            ),
            Check("Pasif varlıkta pay", "warn", "TTE: 2.5 adet (satış girilebilir)"),
        ]


SERIES = "TP.TUKFIY2025.GENEL"


@pytest.mark.parametrize(
    ("stored", "today", "expected"),
    [
        (None, date(2026, 11, 24), Check("TÜFE", "warn", "veri yok; `ft sync cpi` çalıştır")),
        ("2026-10", date(2026, 11, 24), Check("TÜFE", "ok", f"{SERIES} son dönem 2026-10")),
        ("2026-09", date(2026, 11, 2), Check("TÜFE", "ok", f"{SERIES} son dönem 2026-09")),
        (
            "2026-08",
            date(2026, 11, 24),
            Check(
                "TÜFE", "warn", f"{SERIES} son dönem 2026-08; güncel değil, `ft sync cpi` çalıştır"
            ),
        ),
    ],
)
def test_cpi_check(migrated_db: Path, stored: str | None, today: date, expected: Check) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        if stored is not None:
            point = CpiPoint(YearMonth.parse(stored), D(104))
            uow.cpi.upsert(
                SERIES, point, base="2025=100", fetched_at=datetime(2026, 11, 1, tzinfo=UTC)
            )
        assert cpi_check(uow, SERIES, today=today) == expected


TODAY = date(2026, 11, 24)
WEEKDAYS = [date(2026, 11, d) for d in (16, 17, 18, 19, 20, 23, 24)]
FETCHED = datetime(2026, 11, 24, 18, 30, tzinfo=UTC)


def _prices(uow: SqliteUnitOfWork, code: str, days: list[date]) -> None:
    for day in days:
        uow.prices.upsert(PricePoint(code, day, D(10), "tefas"), fetched_at=FETCHED)


def test_price_check_lists_the_last_price_day_of_each_asset(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        assert price_check(uow, today=TODAY) == Check("Fiyatlar", "ok", "takip edilen varlık yok")
        uow.instruments.sync([TTE, XHT, ALTIN])
        _prices(uow, "TTE", WEEKDAYS)
        _prices(uow, "XHT", WEEKDAYS)
        _prices(uow, "ALTIN_GR", [date(2026, 11, 20)])
        assert price_check(uow, today=TODAY) == Check(
            "Fiyatlar", "ok", "son fiyat 2026-11-24: TTE, XHT; 2026-11-20: ALTIN_GR"
        )


def test_stale_or_missing_prices_are_a_warning(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.instruments.sync([TTE, XHT, ALTIN])
        _prices(uow, "TTE", WEEKDAYS)
        _prices(uow, "XHT", WEEKDAYS[:1])
        assert price_check(uow, today=TODAY) == Check(
            "Fiyatlar",
            "warn",
            "son fiyat 2026-11-24: TTE; 2026-11-16: XHT; fiyatı yok: ALTIN_GR; "
            "2 bayatlık uyarısı, ayrıntı için `ft data check`",
        )
