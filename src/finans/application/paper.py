"""Sanal işlem: fiyat yalnızca o günün kaydından, adet domain kuralıyla (K-109, K-116)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from finans.application.report import payday_plan
from finans.application.transactions import add_transaction
from finans.domain.models import DomainError, PricePoint, Side, Transaction
from finans.domain.orders import payday_price_day, payday_window_end, units_for_amount
from finans.domain.portfolio import PortfolioConfig
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


PaydayStatus = Literal["ready", "pending", "expired", "applied", "skipped"]


@dataclass(frozen=True, slots=True)
class PaydayPurchase:
    asset_class: str
    instrument: str
    amount: Decimal
    status: PaydayStatus
    ref: str
    price_day: date | None = None
    price: Decimal | None = None
    units: Decimal | None = None
    spent: Decimal | None = None
    leftover: Decimal | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PaydayPurchasePlan:
    payday: date
    window_end: date
    retry_after: date
    missing_prices: list[str]
    lines: list[PaydayPurchase]


def plan_payday_purchases(
    uow: UnitOfWork, config: PortfolioConfig, *, payday: date, today: date
) -> PaydayPurchasePlan:
    """Plan maaş gününün değerlemesinden; tekrar çalıştırmada değişmez (K-113)."""
    plan = payday_plan(uow, config, on=payday, contribution=config.monthly_contribution)
    window_end = payday_window_end(payday)
    applied = {s.external_ref for s in uow.transactions.list()}
    lines = [
        _purchase(uow, line.asset_class, line.instrument, line.amount, payday, today, applied)
        for line in plan.lines
        if line.amount > 0
    ]
    return PaydayPurchasePlan(
        payday, window_end, today + timedelta(days=1), plan.missing_prices, lines
    )


def record_payday_purchases(
    uow: UnitOfWork, plan: PaydayPurchasePlan, *, now: datetime
) -> list[PaperTrade]:
    return [
        paper_buy(
            uow,
            code=line.instrument,
            amount=line.amount,
            day=line.price_day,
            fee=Decimal(0),
            now=now,
            ref=line.ref,
        )
        for line in plan.lines
        if line.status == "ready" and line.price_day is not None
    ]


def _purchase(
    uow: UnitOfWork,
    asset_class: str,
    code: str,
    amount: Decimal,
    payday: date,
    today: date,
    applied: set[str | None],
) -> PaydayPurchase:
    ref = f"sanal-maas-gunu:{payday.isoformat()}:{code}"
    base = PaydayPurchase(asset_class, code, amount, "applied", ref)
    if ref in applied:
        return base
    _, after = uow.prices.around(code, payday)
    day = payday_price_day(payday, [] if after is None else [after.price_date])
    if day is None or after is None:
        status: PaydayStatus = "pending" if today <= payday_window_end(payday) else "expired"
        return PaydayPurchase(asset_class, code, amount, status, ref)
    stored = uow.instruments.get(code)
    if stored is None:
        return PaydayPurchase(asset_class, code, amount, "skipped", ref, reason="tanımlı değil")
    try:
        split = units_for_amount(amount, after.price, stored.instrument.kind)
    except DomainError as exc:
        return PaydayPurchase(asset_class, code, amount, "skipped", ref, day, reason=str(exc))
    return PaydayPurchase(
        asset_class,
        code,
        amount,
        "ready",
        ref,
        day,
        after.price,
        split.units,
        split.spent,
        split.leftover,
    )
