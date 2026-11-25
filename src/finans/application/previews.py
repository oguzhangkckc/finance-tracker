"""Web önizlemesi: kayıtla aynı ret kuralları, hiçbir şey yazmaz (K-126)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finans.application.data_check import trade_price_issues
from finans.application.transactions import check_transaction, check_void
from finans.domain.models import Side, Transaction
from finans.domain.positions import build_positions
from finans.domain.quality import DataIssue
from finans.ports.repositories import StoredTransaction
from finans.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class TradePreview:
    transaction: Transaction
    ref: str | None
    units_before: Decimal
    units_after: Decimal
    gross: Decimal
    # K-64: TEFAS fiyatıyla tutmayan fiyat engellemez, önizlemede uyarı olarak gösterilir.
    warnings: tuple[DataIssue, ...]


@dataclass(frozen=True, slots=True)
class VoidPreview:
    stored: StoredTransaction


def preview_transaction(
    uow: UnitOfWork, tx: Transaction, *, ref: str | None, today: date
) -> TradePreview:
    existing = check_transaction(uow, tx, ref=ref)
    book = build_positions([s.transaction for s in existing], as_of=date.max)
    before = book.units_of(tx.instrument)
    after = before + tx.units if tx.side is Side.BUY else before - tx.units
    warnings = tuple(trade_price_issues(uow, [("yeni", tx)], today=today))
    return TradePreview(tx, ref, before, after, tx.units * tx.unit_price, warnings)


def preview_void(uow: UnitOfWork, txn_id: int) -> VoidPreview:
    return VoidPreview(check_void(uow, txn_id))
