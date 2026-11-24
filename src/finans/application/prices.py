from datetime import date, datetime
from decimal import Decimal

from finans.domain.models import DomainError, InstrumentKind, PricePoint
from finans.domain.numeric import canonical_text
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
        existing = uow.prices.on(code, on)
        if existing is not None and existing.source == "tefas":
            raise DomainError(
                f"{code} için {on} günü TEFAS fiyatı var ({canonical_text(existing.price)}); "
                "TEFAS fiyatı önceliklidir, elle fiyat girilemez (K-63)."
            )
    return uow.prices.upsert(PricePoint(code, on, price, source="manual"), fetched_at=now)
