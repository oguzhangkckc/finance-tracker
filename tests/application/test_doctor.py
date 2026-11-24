from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.doctor import Check, cpi_check, portfolio_checks
from finans.domain.models import CpiPoint, Instrument, InstrumentKind, Side, Transaction, YearMonth
from finans.domain.portfolio import AlertThresholds, PortfolioConfig

D = Decimal
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")


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
