"""Sanal işlem: fiyat yalnızca o günün kaydından, adet domain kuralıyla (K-109, K-116)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from finans.application.codes import unknown_code_message
from finans.application.report import payday_plan
from finans.application.transactions import add_transaction
from finans.domain.models import DomainError, PricePoint, Side, Transaction
from finans.domain.orders import payday_price_day, payday_window_end, units_for_amount
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.ports.unit_of_work import UnitOfWork


class NoPriceError(DomainError):
    """K-109: o günün kayıtlı fiyatı yok; gün kaydırılmaz. En yakın fiyatlı günler yalnız bilgi
    ve web'de seçenek olarak taşınır; CLI mesajı aynı kalır."""

    def __init__(self, code: str, day: date, before: date | None, after: date | None) -> None:
        nearest = ", ".join(
            f"{label} {nearby.isoformat()}"
            for label, nearby in (("önce", before), ("sonra", after))
            if nearby is not None
        )
        hint = f" En yakın fiyatlı günler: {nearest}." if nearest else " Bu fon için hiç fiyat yok."
        super().__init__(
            f"{code} için {day.isoformat()} tarihli fiyat yok; fiyat uydurulmaz, gün kaydırılmaz."
            f"{hint}"
        )
        self.code = code
        self.day = day
        self.before = before
        self.after = after


@dataclass(frozen=True, slots=True)
class PaperTrade:
    txn_id: int
    code: str
    day: date
    units: Decimal
    price: Decimal
    spent: Decimal
    leftover: Decimal | None


@dataclass(frozen=True, slots=True)
class PaperPlan:
    """Sanal işlemin yazılmadan önceki hali; web önizlemesi ve kayıt aynı planı kullanır."""

    code: str
    day: date
    side: Side
    units: Decimal
    price: Decimal
    spent: Decimal
    leftover: Decimal | None
    fee: Decimal

    @property
    def transaction(self) -> Transaction:
        return Transaction(self.code, self.day, self.side, self.units, self.price, self.fee)


def plan_paper_buy(
    uow: UnitOfWork, *, code: str, amount: Decimal, day: date, fee: Decimal
) -> PaperPlan:
    stored = uow.instruments.get(code)
    if stored is None:
        raise DomainError(unknown_code_message(uow, code))
    point = _price_on(uow, code, day)
    split = units_for_amount(amount, point.price, stored.instrument.kind)
    return PaperPlan(
        code, day, Side.BUY, split.units, point.price, split.spent, split.leftover, fee
    )


def plan_paper_sell(uow: UnitOfWork, *, code: str, units: Decimal | None, day: date) -> PaperPlan:
    """`units` verilmezse o gün eldeki payın tamamı satılır."""
    point = _price_on(uow, code, day)
    if units is None:
        book = build_positions([s.transaction for s in uow.transactions.list()], as_of=day)
        units = book.units_of(code)
        if units <= 0:
            raise DomainError(
                f"{code} için {day.isoformat()} günü elde pay yok; satılacak bir şey yok."
            )
    return PaperPlan(
        code, day, Side.SELL, units, point.price, units * point.price, None, Decimal(0)
    )


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
    plan = plan_paper_buy(uow, code=code, amount=amount, day=day, fee=fee)
    txn_id = add_transaction(uow, plan.transaction, ref=ref, note=None, now=now)
    return PaperTrade(txn_id, code, day, plan.units, plan.price, plan.spent, plan.leftover)


def paper_sell(
    uow: UnitOfWork, *, code: str, units: Decimal, day: date, now: datetime
) -> PaperTrade:
    plan = plan_paper_sell(uow, code=code, units=units, day=day)
    txn_id = add_transaction(uow, plan.transaction, ref=None, note=None, now=now)
    return PaperTrade(txn_id, code, day, plan.units, plan.price, plan.spent, None)


def _price_on(uow: UnitOfWork, code: str, day: date) -> PricePoint:
    point = uow.prices.on(code, day)
    if point is not None:
        return point
    before, after = uow.prices.around(code, day)
    raise NoPriceError(
        code,
        day,
        None if before is None else before.price_date,
        None if after is None else after.price_date,
    )


PaydayStatus = Literal["ready", "nothing", "pending", "expired", "applied", "voided", "skipped"]


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
    uow: UnitOfWork,
    config: PortfolioConfig,
    *,
    payday: date,
    today: date,
    reapply_voided: bool = False,
) -> PaydayPurchasePlan:
    """Plan maaş gününün değerlemesinden; tekrar çalıştırmada değişmez (K-113)."""
    plan = payday_plan(uow, config, on=payday)
    window_end = payday_window_end(payday)
    stored = uow.transactions.list(include_voided=True)
    applied = {s.external_ref for s in stored if not s.is_voided}
    # K-119: iptal bilinçli bir karardır; yalnızca açıkça istenirse yeniden önerilir.
    voided = set() if reapply_voided else {s.external_ref for s in stored if s.is_voided}
    lines = [
        _purchase(
            uow, line.asset_class, line.instrument, line.amount, payday, today, applied, voided
        )
        for line in plan.lines
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
    voided: set[str | None],
) -> PaydayPurchase:
    ref = f"sanal-maas-gunu:{payday.isoformat()}:{code}"
    if amount <= 0:
        return PaydayPurchase(asset_class, code, amount, "nothing", ref)
    base = PaydayPurchase(asset_class, code, amount, "applied", ref)
    if ref in applied:
        return base
    if ref in voided:
        return PaydayPurchase(asset_class, code, amount, "voided", ref)
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
