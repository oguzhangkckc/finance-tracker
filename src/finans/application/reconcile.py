from collections.abc import Sequence
from datetime import date

from finans.application.price_sync import TEFAS_KINDS
from finans.domain.quality import trading_days
from finans.domain.reconcile import ReconcileReport, StatementLine, reconcile
from finans.ports.unit_of_work import UnitOfWork


def reconcile_statement(uow: UnitOfWork, lines: Sequence[StatementLine]) -> ReconcileReport:
    """Ekstreyi kayıtlarla karşılaştırır; değer `ft value --on` ile aynı hesaptan gelir (K-67)."""
    instruments = {
        item.instrument.code: item.instrument
        for item in uow.instruments.list(include_inactive=True)
    }
    prices = uow.prices.history(until=date.max)
    days = trading_days(
        point
        for point in prices
        if point.instrument in instruments and instruments[point.instrument].kind in TEFAS_KINDS
    )
    transactions = [(f"#{stored.id}", stored.transaction) for stored in uow.transactions.list()]
    return reconcile(lines, transactions, prices, days)
