from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

from finans.application.data_check import price_series, tracked_instruments
from finans.application.password import well_formed
from finans.domain.models import YearMonth
from finans.domain.numeric import canonical_text
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.domain.quality import check_staleness
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


def price_check(uow: UnitOfWork, *, today: date) -> Check:
    tracked = tracked_instruments(uow)
    if not tracked:
        return Check("Fiyatlar", "ok", "takip edilen varlık yok")
    history = price_series(uow, today)
    by_day: dict[date, list[str]] = defaultdict(list)
    for instrument in tracked:
        series = history.get(instrument.code)
        if series:
            by_day[max(p.price_date for p in series)].append(instrument.code)
    parts = [f"{day}: {', '.join(sorted(codes))}" for day, codes in sorted(by_day.items())[::-1]]
    details = [f"son fiyat {'; '.join(parts)}"] if parts else []
    missing = sorted(i.code for i in tracked if not history.get(i.code))
    if missing:
        details.append(f"fiyatı yok: {', '.join(missing)}")
    issues = check_staleness(tracked, history, today=today)
    if not issues:
        return Check("Fiyatlar", "ok", "; ".join(details))
    details.append(f"{len(issues)} bayatlık uyarısı, ayrıntı için `ft data check`")
    return Check("Fiyatlar", "warn", "; ".join(details))


def web_password_check(stored: str | None) -> Check:
    """`stored` credstore'daki dosyanın içeriğidir, dosya yoksa None; değer gösterilmez (K-126)."""
    name = "Web yazma şifresi"
    if stored is None:
        return Check(
            name, "fail", "credstore'da yok; finans-web başlamaz. Kurulum 11.3: `ft web sifre`"
        )
    if not stored.strip():
        return Check(name, "warn", "dosya boş; web'de yazma kapalı")
    if well_formed(stored):
        return Check(name, "ok", "geçerli scrypt özeti")
    return Check(
        name,
        "fail",
        "scrypt özeti değil; finans-web başlamaz. `ft web sifre` ile yeniden üret",
    )
