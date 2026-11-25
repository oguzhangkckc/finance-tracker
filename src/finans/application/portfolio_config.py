from dataclasses import dataclass
from datetime import date, datetime

from finans.application.settings import sync_settings
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.ports.repositories import InstrumentSync
from finans.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ApplyReport:
    sync: InstrumentSync
    warnings: tuple[str, ...]
    settings: tuple[str, ...] = ()


def apply_portfolio(
    uow: UnitOfWork, config: PortfolioConfig, *, today: date, at: datetime
) -> ApplyReport:
    """Varlıklar ve ayarlar tek işlemde; ayar reddedilirse varlık değişikliği de geri alınır."""
    sync = uow.instruments.sync(config.instruments)
    settings = sync_settings(uow, config, today=today, at=at)
    return ApplyReport(sync, _holding_warnings(uow, sync) + settings.warnings, settings.notes)


def _holding_warnings(uow: UnitOfWork, sync: InstrumentSync) -> tuple[str, ...]:
    if not sync.deactivated:
        return ()
    book = build_positions([s.transaction for s in uow.transactions.list()], as_of=date.max)
    return tuple(
        f"{code} pasif yapıldı ama elde {format(book.units_of(code), 'f')} adet var;"
        " satış girilebilir, alış girilemez."
        for code in sync.deactivated
        if book.units_of(code) > 0
    )
