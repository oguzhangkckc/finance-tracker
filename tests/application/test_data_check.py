from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.data_check import check_data, tracked_instruments, trade_price_issues
from finans.domain.models import Instrument, InstrumentKind, PricePoint, Side, Transaction
from finans.domain.portfolio import QualityThresholds

D = Decimal
NOW = datetime(2026, 11, 24, 18, 30, tzinfo=UTC)
TODAY = date(2026, 11, 24)
XHT = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse_tr")
XPP = Instrument("XPP", InstrumentKind.TEFAS_YAT, "dusuk_risk", category="para_piyasasi")
OLD = Instrument("OLD", InstrumentKind.TEFAS_YAT, "hisse_tr")
GOLD = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")
DAYS = [date(2026, 11, d) for d in (17, 18, 19, 20, 23, 24)]


@pytest.fixture
def db(migrated_db: Path) -> Path:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.instruments.sync([XHT, XPP, OLD, GOLD])
        for day, aku, bgp in zip(
            DAYS, ("1.7", "1.71", "1.72", "1.744322", "1.73", "1.715559"), "777778", strict=True
        ):
            uow.prices.upsert(PricePoint("XHT", day, D(aku), "tefas"), fetched_at=NOW)
            uow.prices.upsert(PricePoint("XPP", day, D(bgp), "tefas"), fetched_at=NOW)
        uow.prices.upsert(PricePoint("OLD", DAYS[0], D(5), "tefas"), fetched_at=NOW)
        uow.transactions.add(
            Transaction("XHT", date(2026, 11, 23), Side.BUY, D(10), D("1.7443")),
            external_ref=None,
            note=None,
            created_at=NOW,
        )
        uow.instruments.sync([XHT, XPP, GOLD])
    return migrated_db


def test_data_check_covers_tracked_instruments_and_stored_trades(db: Path) -> None:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        issues = check_data(uow, quality=QualityThresholds(), today=TODAY, since=date(2026, 11, 1))

    # OLD pasif ve elde pay yok: denetlenmez. XHT'nun 23.11 işlemi 20.11 fiyatıyla eşleşiyor.
    assert [str(issue) for issue in issues] == [
        "[bayatlık] ALTIN_GR: hiç fiyat girilmemiş; `ft price set` ile gir",
        "[sıçrama] XPP 2026-11-24: günlük değişim %14.29 (eşik %1; önceki 2026-11-23: 7)",
        "[işlem fiyatı] XHT 2026-11-23 #1: fiyat 1.7443 o günün TEFAS fiyatıyla (1.73) "
        "uyuşmuyor (fark %0.83); 2026-11-20 gününün fiyatıyla (1.744322) eşleşiyor, "
        "tarih büyük olasılıkla 2026-11-20",
    ]


def test_new_entries_are_checked_with_the_digits_as_entered(db: Path) -> None:
    four_digits = Transaction("XHT", date(2026, 11, 19), Side.BUY, D(1), D("1.7200"))
    two_digits = Transaction("XHT", date(2026, 11, 19), Side.BUY, D(1), D("1.72"))
    with SqliteUnitOfWork(db, readonly=True) as uow:
        checked = trade_price_issues(uow, [("satır 2", four_digits)], today=TODAY)
        noted = trade_price_issues(uow, [("satır 3", two_digits)], today=TODAY)

    # Kayıtta sondaki sıfırlar düşer; girişte 1.7200 dört basamaklı sayılır ve 1.72 ile eşleşir.
    assert checked == []
    assert [issue.level for issue in noted] == ["info"]


def test_stored_trades_use_the_entered_digits_and_fall_back_without_them(db: Path) -> None:
    with SqliteUnitOfWork(db) as uow:
        uow.transactions.add(
            Transaction("XHT", date(2026, 11, 19), Side.BUY, D(1), D("1.7200")),
            external_ref=None,
            note=None,
            created_at=NOW,
        )
    with closing(connect(db)) as conn:
        conn.execute(
            "INSERT INTO txn (instrument_id, trade_date, side, units, unit_price, created_at)"
            " SELECT id, '2026-11-19', 'BUY', '1', '1.72', '2026-11-24T00:00:00+00:00'"
            " FROM instrument WHERE code = 'XHT'"
        )

    with SqliteUnitOfWork(db, readonly=True) as uow:
        issues = check_data(uow, quality=QualityThresholds(), today=TODAY, since=date(2026, 11, 1))

    trade_issues = [issue for issue in issues if issue.check == "işlem fiyatı"]
    # #2 (1.7200, 4 basamak) eşleşir; #3 basamak sayısı olmadan kayıtlı, 2 basamak sayılır.
    # Sorunlar işlem tarihine göre sıralı: #3 (19.11), #1 (23.11).
    assert [(issue.ref, issue.level) for issue in trade_issues] == [("#3", "info"), ("#1", "warn")]


def test_only_trades_up_to_the_checked_day_are_checked(db: Path) -> None:
    with SqliteUnitOfWork(db) as uow:
        uow.transactions.add(
            Transaction("OLD", date(2026, 11, 17), Side.BUY, D(1), D(5)),
            external_ref=None,
            note=None,
            created_at=NOW,
        )
        uow.transactions.add(
            Transaction("OLD", date(2026, 11, 23), Side.SELL, D(1), D(5)),
            external_ref=None,
            note=None,
            created_at=NOW,
        )

    with SqliteUnitOfWork(db, readonly=True) as uow:
        issues = check_data(
            uow, quality=QualityThresholds(), today=date(2026, 11, 20), since=date(2026, 11, 1)
        )
        on_20th = [i.code for i in tracked_instruments(uow, as_of=date(2026, 11, 20))]
        now = [i.code for i in tracked_instruments(uow)]

    assert not [str(issue) for issue in issues if "2026-11-23" in str(issue)]
    # OLD pasif; 20.11'de hâlâ elde, o günün denetiminde izlenir; satıştan sonra izlenmez.
    assert "OLD" in on_20th
    assert "OLD" not in now
