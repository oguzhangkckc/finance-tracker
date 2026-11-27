from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

from finans.application.data_check import price_series, tracked_instruments
from finans.application.settings import active_versions, toml_warning
from finans.domain.models import YearMonth
from finans.domain.numeric import canonical_text
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.domain.quality import check_staleness
from finans.domain.settings import class_changes, effective_version
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


def settings_check(uow: UnitOfWork, config: PortfolioConfig, *, today: date) -> Check:
    """Ayarın değeri gösterilmez; yalnız sürüm günleri ve farklı olan ayarın adı (K-127)."""
    name = "Ayarlar"
    versions = active_versions(uow)
    current = effective_version(versions, today)
    if current is None:
        return Check(
            name, "warn", "sürüm yok, portfolio.toml kullanılıyor; `ft config apply` çalıştır"
        )
    changes = class_changes(versions, config.targets.keys(), today=today)
    if changes.blocked:
        return Check(
            name,
            "warn",
            "`ft config apply` reddeder: ağırlığı 0 olmayan sınıf silinmiş"
            f" ({', '.join(changes.blocked)}); önce ağırlığını 0 yap.",
        )
    parts: list[str] = []
    if changes.added or changes.removed:
        listed = [f"eklenecek sınıf: {', '.join(changes.added)}"] * bool(changes.added)
        listed += [f"çıkarılacak sınıf: {', '.join(changes.removed)}"] * bool(changes.removed)
        parts.append(f"`ft config apply` gerekli; {'; '.join(listed)}.")
    warning = toml_warning(current, config)
    if warning is not None:
        parts.append(warning)
    if parts:
        return Check(name, "warn", " ".join(parts))
    if current.effective_from == date.min:
        detail = "başlangıç sürümü (portfolio.toml)"
    else:
        detail = f"yürürlükteki sürüm: {current.effective_from.isoformat()}"
    planned = sorted({v.effective_from.isoformat() for v in versions if v.effective_from > today})
    if planned:
        detail += f"; planlanan: {', '.join(planned)}"
    return Check(name, "ok", detail)


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
