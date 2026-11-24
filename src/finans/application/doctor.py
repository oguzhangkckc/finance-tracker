from dataclasses import dataclass
from datetime import date
from typing import Literal

from finans.domain.models import YearMonth
from finans.domain.numeric import canonical_text
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.ports.unit_of_work import UnitOfWork

Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    detail: str


def portfolio_checks(uow: UnitOfWork, config: PortfolioConfig) -> list[Check]:
    return [_sync_check(uow, config), inactive_holdings_check(uow)]


def _sync_check(uow: UnitOfWork, config: PortfolioConfig) -> Check:
    active = {s.instrument.code: s.instrument for s in uow.instruments.list()}
    wanted = {instrument.code: instrument for instrument in config.instruments}
    differences = [
        (label, codes)
        for label, codes in (
            ("eklenecek", sorted(wanted.keys() - active.keys())),
            ("pasif yapılacak", sorted(active.keys() - wanted.keys())),
            ("farklı", sorted(c for c in wanted.keys() & active.keys() if wanted[c] != active[c])),
        )
        if codes
    ]
    if not differences:
        return Check("Config ile veritabanı", "ok", "uyumlu")
    detail = "; ".join(f"{label}: {', '.join(codes)}" for label, codes in differences)
    return Check("Config ile veritabanı", "warn", f"`ft config apply` gerekli; {detail}")


def inactive_holdings_check(uow: UnitOfWork) -> Check:
    inactive = [
        s.instrument.code for s in uow.instruments.list(include_inactive=True) if not s.active
    ]
    book = build_positions([s.transaction for s in uow.transactions.list()], as_of=date.max)
    held = [
        f"{code}: {canonical_text(book.units_of(code))} adet"
        for code in inactive
        if book.units_of(code) > 0
    ]
    if not held:
        return Check("Pasif varlıkta pay", "ok", "yok")
    return Check("Pasif varlıkta pay", "warn", f"{'; '.join(held)} (satış girilebilir)")


def cpi_check(uow: UnitOfWork, series: str, *, today: date) -> Check:
    latest = uow.cpi.latest(series)
    if latest is None:
        return Check("TÜFE", "warn", "veri yok; `ft sync cpi` çalıştır")
    # t ayının TÜFE'si t+1 ayının başında açıklanır; iki aydan eskisi kaçırılmış bir yayındır.
    if latest.period < YearMonth.of(today).shift(-2):
        return Check(
            "TÜFE",
            "warn",
            f"{series} son dönem {latest.period}; güncel değil, `ft sync cpi` çalıştır",
        )
    return Check("TÜFE", "ok", f"{series} son dönem {latest.period}")
