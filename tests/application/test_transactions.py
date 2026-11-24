from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.transactions import (
    add_transaction,
    import_transactions,
    void_transaction,
)
from finans.domain.models import DomainError, Instrument, InstrumentKind, Side, Transaction
from finans.ports.sources import ImportIssue, ImportRow, ParsedTransactions

D = Decimal
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")


def tx(
    day: str, side: Side = Side.BUY, units: str = "10", price: str = "10", code: str = "TTE"
) -> Transaction:
    return Transaction(code, date.fromisoformat(day), side, D(units), D(price))


@pytest.fixture
def uow(migrated_db: Path) -> Iterator[SqliteUnitOfWork]:
    with SqliteUnitOfWork(migrated_db) as work:
        work.instruments.sync([TTE, ALTIN])
        yield work


def _add(uow: SqliteUnitOfWork, transaction: Transaction, ref: str | None = None) -> int:
    return add_transaction(uow, transaction, ref=ref, note=None, now=NOW)


class TestAdd:
    def test_unknown_instrument_is_rejected_with_a_hint(self, uow: SqliteUnitOfWork) -> None:
        with pytest.raises(DomainError, match=r"YOK tanımlı değil.*ft config apply"):
            _add(uow, tx("2026-01-05", code="YOK"))

    def test_inactive_instrument_accepts_sells_but_not_buys(self, uow: SqliteUnitOfWork) -> None:
        _add(uow, tx("2026-01-05"))
        uow.instruments.sync([ALTIN])
        _add(uow, tx("2026-02-05", Side.SELL, units="4"))
        with pytest.raises(DomainError, match="TTE pasif"):
            _add(uow, tx("2026-03-05"))

    def test_backdated_sell_that_breaks_a_later_sell_is_rejected(
        self, uow: SqliteUnitOfWork
    ) -> None:
        _add(uow, tx("2026-01-10"))
        _add(uow, tx("2026-01-20", Side.SELL, units="6"))
        with pytest.raises(DomainError, match="TTE"):
            _add(uow, tx("2026-01-15", Side.SELL, units="5"))

    def test_active_reference_must_be_unique(self, uow: SqliteUnitOfWork) -> None:
        _add(uow, tx("2026-01-05"), ref="R1")
        with pytest.raises(DomainError, match="R1"):
            _add(uow, tx("2026-01-06"), ref="R1")


class TestVoid:
    def test_void_hides_the_transaction_and_allows_reentry(self, uow: SqliteUnitOfWork) -> None:
        txn_id = _add(uow, tx("2026-01-05"), ref="R1")
        void_transaction(uow, txn_id, reason="yanlış tarih", now=NOW)
        assert uow.transactions.list() == []
        _add(uow, tx("2026-01-06"), ref="R1")

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_reason_is_required(self, uow: SqliteUnitOfWork, reason: str) -> None:
        txn_id = _add(uow, tx("2026-01-05"))
        with pytest.raises(DomainError, match="gerekçe"):
            void_transaction(uow, txn_id, reason=reason, now=NOW)

    def test_unknown_or_already_voided(self, uow: SqliteUnitOfWork) -> None:
        txn_id = _add(uow, tx("2026-01-05"))
        void_transaction(uow, txn_id, reason="yanlış", now=NOW)
        with pytest.raises(DomainError, match="zaten iptal"):
            void_transaction(uow, txn_id, reason="yanlış", now=NOW)
        with pytest.raises(DomainError, match="999"):
            void_transaction(uow, 999, reason="yanlış", now=NOW)

    def test_void_that_would_break_a_later_sell_is_rejected(self, uow: SqliteUnitOfWork) -> None:
        buy = _add(uow, tx("2026-01-05"))
        sell = _add(uow, tx("2026-02-05", Side.SELL))
        with pytest.raises(DomainError) as failure:
            void_transaction(uow, buy, reason="yanlış", now=NOW)
        assert str(failure.value) == (
            f"{buy} numaralı işlem iptal edilemez; sonraki satışlar elde olmayan payı satmış "
            f"olur. Önce şu satışları `ft tx void` ile iptal et: #{sell} (2026-02-05 TTE 10 adet)."
        )

    def test_rejected_void_lists_every_sell_to_void_first(self, uow: SqliteUnitOfWork) -> None:
        _add(uow, tx("2026-01-05", units="10"))
        wrong = _add(uow, tx("2026-01-10", units="10"))
        _add(uow, tx("2026-01-20", Side.SELL, units="8"))
        first = _add(uow, tx("2026-02-05", Side.SELL, units="5"))
        second = _add(uow, tx("2026-02-05", Side.SELL, units="1"))
        _add(uow, tx("2026-02-01", units="1", price="3000", code="ALTIN_GR"))
        _add(uow, tx("2026-02-05", Side.SELL, units="1", price="3100", code="ALTIN_GR"))
        _add(uow, tx("2026-03-01", Side.SELL, units="2"))
        third = _add(uow, tx("2026-03-02", Side.SELL, units="1.5"))

        # İptal sonrası elde 10 kalır; 01-20'de 2'ye iner. 02-05'in 6 adedi karşılanamaz ve
        # yok sayılır; 03-01 elde kalan 2'yi bitirir, 03-02'nin 1.5 adedi de karşılanamaz.
        with pytest.raises(DomainError, match="ile iptal et: #") as failure:
            void_transaction(uow, wrong, reason="yanlış", now=NOW)
        assert str(failure.value).endswith(
            f"#{first} (2026-02-05 TTE 5 adet), #{second} (2026-02-05 TTE 1 adet), "
            f"#{third} (2026-03-02 TTE 1.5 adet)."
        )

        for sell in (first, second, third):
            void_transaction(uow, sell, reason="alış yanlış", now=NOW)
        void_transaction(uow, wrong, reason="yanlış", now=NOW)
        assert uow.transactions.get(wrong).is_voided  # type: ignore[union-attr]


def _parsed(
    *rows: tuple[Transaction, str | None], issues: tuple[ImportIssue, ...] = ()
) -> ParsedTransactions:
    return ParsedTransactions(
        tuple(ImportRow(line, t, ref, None) for line, (t, ref) in enumerate(rows, start=2)), issues
    )


def _messages(report_issues: tuple[ImportIssue, ...]) -> list[str]:
    return [str(issue) for issue in report_issues]


class TestImport:
    def test_rows_are_added_and_a_rerun_skips_them(self, uow: SqliteUnitOfWork) -> None:
        parsed = _parsed((tx("2026-01-05"), "R1"), (tx("2026-01-06"), None))
        first = import_transactions(uow, parsed, now=NOW, dry_run=False)
        assert (len(first.added), len(first.skipped), first.issues) == (2, 0, ())
        refs = [s.external_ref for s in uow.transactions.list()]
        assert refs[0] == "R1"
        assert refs[1] is not None
        assert refs[1].startswith("sha256:")
        second = import_transactions(uow, parsed, now=NOW, dry_run=False)
        assert (len(second.added), len(second.skipped)) == (0, 2)

    def test_dry_run_writes_nothing(self, uow: SqliteUnitOfWork) -> None:
        report = import_transactions(uow, _parsed((tx("2026-01-05"), None)), now=NOW, dry_run=True)
        assert len(report.added) == 1
        assert uow.transactions.list() == []

    def test_same_reference_with_different_content_stops_the_import(
        self, uow: SqliteUnitOfWork
    ) -> None:
        txn_id = _add(uow, tx("2026-01-05"), ref="R1")
        parsed = _parsed((tx("2026-01-05", price="11"), "R1"), (tx("2026-01-07"), None))
        report = import_transactions(uow, parsed, now=NOW, dry_run=False)
        assert _messages(report.issues) == [
            f"satır 2: R1 ref'i mevcut #{txn_id} kaydında farklı içerikle var; "
            f"düzeltmek için önce `ft tx void {txn_id}` ile iptal et."
        ]
        assert len(uow.transactions.list()) == 1

    def test_possible_correction_against_an_existing_record(self, uow: SqliteUnitOfWork) -> None:
        txn_id = _add(uow, tx("2026-01-05"))
        report = import_transactions(
            uow, _parsed((tx("2026-01-05", price="10.5"), None)), now=NOW, dry_run=False
        )
        assert _messages(report.issues) == [
            f"satır 2: olası düzeltme ya da çift kayıt: mevcut #{txn_id} kaydıyla tarih, kod, yön "
            "ve adet aynı ama içerik farklı."
        ]

    def test_problems_inside_the_file(self, uow: SqliteUnitOfWork) -> None:
        parsed = _parsed(
            (tx("2026-01-05"), None),
            (tx("2026-01-05"), None),
            (tx("2026-01-08"), None),
            (tx("2026-01-08", price="11"), None),
        )
        report = import_transactions(uow, parsed, now=NOW, dry_run=False)
        assert _messages(report.issues) == [
            "satır 3: satır 2 ile birebir aynı ve ref'siz; aynı gün aynı işlem gerçekten iki kez "
            "yapıldıysa ref sütununu doldur.",
            "satır 5: olası düzeltme ya da çift kayıt: satır 4 ile tarih, kod, yön ve adet aynı "
            "ama içerik farklı.",
        ]
        assert uow.transactions.list() == []

    def test_identical_rows_with_distinct_references_are_both_added(
        self, uow: SqliteUnitOfWork
    ) -> None:
        report = import_transactions(
            uow, _parsed((tx("2026-01-05"), "A"), (tx("2026-01-05"), "B")), now=NOW, dry_run=False
        )
        assert (len(report.added), report.issues) == (2, ())

    def test_parse_issues_oversell_and_inactive_buys_stop_the_import(
        self, uow: SqliteUnitOfWork
    ) -> None:
        uow.instruments.sync([ALTIN])
        parsed = _parsed(
            (tx("2026-01-05", code="TTE"), None),
            (tx("2026-01-06", Side.SELL, code="ALTIN_GR"), None),
            issues=(ImportIssue(7, "date: YYYY-AA-GG olmalı"),),
        )
        report = import_transactions(uow, parsed, now=NOW, dry_run=False)
        messages = _messages(report.issues)
        assert messages[0] == "satır 7: date: YYYY-AA-GG olmalı"
        assert "satır 2: TTE pasif; alış girilemez, yalnızca satış girilebilir." in messages
        assert any("ALTIN_GR" in m and "satılmak isteniyor" in m for m in messages)
        assert uow.transactions.list() == []
