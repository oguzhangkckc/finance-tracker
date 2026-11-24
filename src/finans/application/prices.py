from datetime import date, datetime
from decimal import Decimal

from finans.domain.models import DomainError, InstrumentKind, PricePoint
from finans.ports.repositories import PriceWrite
from finans.ports.unit_of_work import UnitOfWork


def set_manual_price(
    uow: UnitOfWork, code: str, on: date, price: Decimal, *, now: datetime
) -> PriceWrite:
    stored = uow.instruments.get(code)
    if stored is None:
        raise DomainError(
            f"{code} tanımlı değil; portfolio.toml'a ekleyip `ft config apply` çalıştır."
        )
    if stored.instrument.kind is not InstrumentKind.MANUAL:
        raise DomainError(f"{code} bir TEFAS fonu; fiyatı elle girilemez, TEFAS'tan çekilir (M3).")
    return uow.prices.upsert(PricePoint(code, on, price, source="manual"), fetched_at=now)
