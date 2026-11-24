"""Sanal işlem: fiyat yalnızca o günün kaydından, adet domain kuralıyla (K-109, K-116)."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from finans.application.transactions import add_transaction
from finans.domain.models import DomainError, PricePoint, Side, Transaction
from finans.domain.orders import units_for_amount
from finans.ports.unit_of_work import UnitOfWork


class NoPriceError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class PaperTrade:
    txn_id: int
    code: str
    day: date
    units: Decimal
    price: Decimal
    spent: Decimal
    leftover: Decimal | None


def paper_buy(
    uow: UnitOfWork,
    *,
    code: str,
    amount: Decimal,
    day: date,
    fee: Decimal,
    now: datetime,
    ref: str | None = None,
) -> PaperTrade:
    stored = uow.instruments.get(code)
    if stored is None:
        raise DomainError(
            f"{code} tanımlı değil; portfolio.toml'a ekleyip `ft config apply` çalıştır."
        )
    point = _price_on(uow, code, day)
    split = units_for_amount(amount, point.price, stored.instrument.kind)
    tx = Transaction(code, day, Side.BUY, split.units, point.price, fee)
    txn_id = add_transaction(uow, tx, ref=ref, note=None, now=now)
    return PaperTrade(txn_id, code, day, split.units, point.price, split.spent, split.leftover)


def paper_sell(
    uow: UnitOfWork, *, code: str, units: Decimal, day: date, now: datetime
) -> PaperTrade:
    point = _price_on(uow, code, day)
    tx = Transaction(code, day, Side.SELL, units, point.price, Decimal(0))
    txn_id = add_transaction(uow, tx, ref=None, note=None, now=now)
    return PaperTrade(txn_id, code, day, units, point.price, units * point.price, None)


def _price_on(uow: UnitOfWork, code: str, day: date) -> PricePoint:
    point = uow.prices.on(code, day)
    if point is not None:
        return point
    before, after = uow.prices.around(code, day)
    nearest = ", ".join(
        f"{label} {p.price_date.isoformat()}"
        for label, p in (("önce", before), ("sonra", after))
        if p is not None
    )
    hint = f" En yakın fiyatlı günler: {nearest}." if nearest else " Bu fon için hiç fiyat yok."
    raise NoPriceError(
        f"{code} için {day.isoformat()} tarihli fiyat yok; fiyat uydurulmaz, gün kaydırılmaz.{hint}"
    )
