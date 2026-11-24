"""Sanal işlemin pay adedi ve fiyat günü; kurallar yalnızca burada değişir (K-109, K-113)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Final

from finans.domain.models import DomainError, InstrumentKind
from finans.domain.numeric import in_domain_context

# Açık soru: TEFAS fonlarında pay adedi tam sayı mı? İlk gerçek dekontla doğrulanacak.
UNIT_PLACES: Final[Mapping[InstrumentKind, int]] = {
    InstrumentKind.TEFAS_YAT: 0,
    InstrumentKind.TEFAS_BYF: 0,
}
# Açık soru "D tarihli fiyat": emir bir sonraki açıklanan fiyattan gerçekleşir varsayımı.
PAYDAY_PRICE_WINDOW: Final = timedelta(days=10)


@dataclass(frozen=True, slots=True)
class AmountSplit:
    units: Decimal
    spent: Decimal
    leftover: Decimal


@in_domain_context
def units_for_amount(amount: Decimal, price: Decimal, kind: InstrumentKind) -> AmountSplit:
    if kind not in UNIT_PLACES:
        raise DomainError(f"{kind.value} için tutarla işlem desteklenmiyor")
    if amount <= 0 or price <= 0:
        raise DomainError(f"Tutar ve fiyat sıfırdan büyük olmalı: {amount}, {price}")
    step = Decimal(1).scaleb(-UNIT_PLACES[kind])
    units = (amount / price).quantize(step, rounding=ROUND_FLOOR)
    # Bölüm 28 basamakta yuvarlanır; yukarı yuvarlanmış bir bölüm tutarı aşmasın.
    if units * price > amount:
        units -= step
    if units <= 0:
        raise DomainError(f"Tutar ({amount}) bir payın fiyatından ({price}) az; en az bir pay")
    spent = units * price
    return AmountSplit(units=units, spent=spent, leftover=amount - spent)


@in_domain_context
def payday_window_end(payday: date) -> date:
    return payday + PAYDAY_PRICE_WINDOW


@in_domain_context
def payday_price_day(payday: date, price_days: Iterable[date]) -> date | None:
    """Maaş gününden sonraki ilk fiyatlı gün; aynı günün fiyatı geleceği görmek olurdu."""
    end = payday_window_end(payday)
    return min((day for day in price_days if payday < day <= end), default=None)
