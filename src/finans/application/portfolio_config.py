from dataclasses import dataclass
from datetime import date

from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.ports.repositories import InstrumentSync
from finans.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ApplyReport:
    sync: InstrumentSync
    warnings: tuple[str, ...]


def apply_portfolio(uow: UnitOfWork, config: PortfolioConfig) -> ApplyReport:
    sync = uow.instruments.sync(config.instruments)
    if not sync.deactivated:
        return ApplyReport(sync, ())
    book = build_positions([s.transaction for s in uow.transactions.list()], as_of=date.max)
    warnings = tuple(
        f"{code} pasif yapıldı ama elde {format(book.units_of(code), 'f')} adet var;"
        " satış girilebilir, alış girilemez."
        for code in sync.deactivated
        if book.units_of(code) > 0
    )
    return ApplyReport(sync, warnings)
