from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.doctor import Check, portfolio_checks
from finans.domain.models import Instrument, InstrumentKind, Side, Transaction
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
