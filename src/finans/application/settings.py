"""Yürürlük tarihli ayarlar (K-127). Sürüm yoksa portfolio.toml geçerlidir; ilk `config apply`
başlangıç sürümünü yazana kadar davranış değişmez. Her okuyucu ilgili günün sürümünü kullanır:
rapor mantıksal gününü, maaş günü planı maaş gününü, alarm değerlendirildiği günü."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Final, Literal

from finans.domain.models import DomainError, YearMonth
from finans.domain.portfolio import ConfigError, ConfigIssue, PortfolioConfig
from finans.domain.schedule import payday_on
from finans.domain.settings import (
    ClassChanges,
    SettingField,
    SettingVersion,
    changed_fields,
    check_version,
    class_changes,
    effective_version,
    payday_schedule,
    reverting_versions,
    start_version,
    toml_differences,
    with_classes,
)
from finans.ports.repositories import SettingSource, StoredSetting
from finans.ports.unit_of_work import UnitOfWork


class FromSettings(Enum):
    """Katkı parametresinin varsayılanı: o günün ayarı. CLI'daki --contribution üzerine yazar."""

    VALUE = "ayar"


FROM_SETTINGS: Final = FromSettings.VALUE


def active_versions(uow: UnitOfWork) -> list[SettingVersion]:
    return [stored.version for stored in uow.settings.list() if not stored.is_cancelled]


def effective_config(uow: UnitOfWork, toml: PortfolioConfig, *, on: date) -> PortfolioConfig:
    version = effective_version(active_versions(uow), on)
    if version is None:
        return toml
    return replace(
        toml,
        payday=version.payday,
        monthly_contribution=version.monthly_contribution,
        targets=dict(version.targets),
    )


def planned_contributions(
    uow: UnitOfWork, toml: PortfolioConfig, months: Sequence[YearMonth]
) -> dict[YearMonth, Decimal | None]:
    """Her ayın planlanan katkısı o ayın maaş gününde yürürlükte olan sürümden; maaş günü
    tanımsız aylarda ayın 1'indekinden. Sürüm yoksa portfolio.toml."""
    versions = active_versions(uow)
    schedule = payday_schedule(versions, fallback=toml.payday)
    planned: dict[YearMonth, Decimal | None] = {}
    for month in months:
        payday = schedule(month)
        day = (
            date(month.year, month.month, 1)
            if payday is None
            else payday_on(month.year, month.month, payday)
        )
        version = effective_version(versions, day)
        planned[month] = (
            toml.monthly_contribution if version is None else version.monthly_contribution
        )
    return planned


def payday_for(uow: UnitOfWork, toml: PortfolioConfig) -> Callable[[YearMonth], int | None]:
    """Her ayın maaş günü o ayın 1'indeki sürümden; maaş günü işinin mantıksal günü buna göre."""
    return payday_schedule(active_versions(uow), fallback=toml.payday)


class Keep(Enum):
    """Yeni sürümde bu ayar, yürürlük gününde geçerli olan sürümdeki değeriyle kalır."""

    VALUE = "aynı"


KEEP: Final = Keep.VALUE


@dataclass(frozen=True, slots=True)
class LaterRewrite:
    """Değişikliği eski değeriyle geri alacak ileri tarihli sürüm ve değişikliği taşıyan hâli."""

    stored: StoredSetting
    fields: tuple[SettingField, ...]
    rewritten: SettingVersion


@dataclass(frozen=True, slots=True)
class Proposal:
    version: SettingVersion
    base: SettingVersion
    changed: tuple[SettingField, ...]
    later: tuple[LaterRewrite, ...]
    issues: tuple[ConfigIssue, ...]


def propose(
    uow: UnitOfWork,
    toml: PortfolioConfig,
    *,
    effective_from: date,
    today: date,
    payday: int | Keep | None = KEEP,
    contribution: Decimal | Keep | None = KEEP,
    targets: Mapping[str, Decimal] | Keep = KEEP,
) -> Proposal:
    """Değişmeyen ayarlar yürürlük gününde geçerli olan sürümden alınır; bugünkünden değil, yoksa
    araya planlanmış bir sürümün değişikliği geri alınırdı."""
    active = [s for s in uow.settings.list() if not s.is_cancelled]
    versions = [s.version for s in active]
    current = effective_version(versions, today)
    if current is None:
        raise DomainError("Ayarların başlangıç sürümü yok; önce `ft config apply` çalıştır.")
    base = effective_version(versions, effective_from) or current
    new = SettingVersion(
        effective_from,
        base.payday if isinstance(payday, Keep) else payday,
        base.monthly_contribution if isinstance(contribution, Keep) else contribution,
        dict(base.targets) if isinstance(targets, Keep) else dict(targets),
    )
    changed = changed_fields(base, new)
    issues = check_version(new, versions=versions, classes=toml.targets.keys(), today=today)
    if not changed:
        issues.append(ConfigIssue("ayar", "o günkü ayarla aynı; yeni sürüm gerekmiyor."))
    later = tuple(
        LaterRewrite(active[revert.index], revert.fields, revert.carried)
        for revert in reverting_versions(new, base, versions, changed)
    )
    return Proposal(new, base, changed, later, tuple(issues))


@dataclass(frozen=True, slots=True)
class Saved:
    """`rewritten`: (vazgeçilen sürüm, yerine yazılan sürüm) çiftleri."""

    setting_id: int
    rewritten: tuple[tuple[int, int], ...]


def save_proposal(
    uow: UnitOfWork,
    toml: PortfolioConfig,
    proposal: Proposal,
    *,
    source: SettingSource,
    today: date,
    at: datetime,
    carry_later: bool,
) -> Saved:
    """`carry_later`: değişikliği geri alacak her ileri tarihli sürümden vazgeçilir ve aynı
    yürürlük günüyle, yalnız değişen ayar güncellenmiş olarak yeniden yazılır. Hepsi çağıranın
    tek işleminde; biri reddedilirse hiçbiri kalmaz."""
    if proposal.issues:
        raise ConfigError(proposal.issues)
    setting_id = add_version(uow, toml, proposal.version, source=source, today=today, at=at)
    rewritten: list[tuple[int, int]] = []
    if carry_later:
        for later in proposal.later:
            reason = f"yeni değişiklik taşındı: #{setting_id}"
            uow.settings.cancel(later.stored.id, reason=reason, at=at)
            new_id = add_version(uow, toml, later.rewritten, source=source, today=today, at=at)
            rewritten.append((later.stored.id, new_id))
    return Saved(setting_id, tuple(rewritten))


SettingState = Literal["in_force", "past", "planned", "replaced", "cancelled"]
STATE_LABELS: Final[Mapping[SettingState, str]] = {
    "in_force": "geçerli",
    "past": "geçmiş",
    "planned": "planlandı",
    "replaced": "aynı gün yenisi kaydedildi",
    "cancelled": "vazgeçildi",
}


@dataclass(frozen=True, slots=True)
class HistoryRow:
    """`previous`: bu sürüm kaydedilmeseydi o gün geçerli olacak sürüm; başlangıçta None."""

    stored: StoredSetting
    state: SettingState
    previous: SettingVersion | None
    changed: tuple[SettingField, ...]


def setting_history(uow: UnitOfWork, *, today: date) -> list[HistoryRow]:
    rows = uow.settings.list()
    active = [s for s in rows if not s.is_cancelled]
    current = effective_version([s.version for s in active], today)
    history: list[HistoryRow] = []
    for stored in rows:
        day = stored.version.effective_from
        before = [
            s.version
            for s in active
            if s.version.effective_from < day
            or (s.version.effective_from == day and s.id < stored.id)
        ]
        previous = effective_version(before, day)
        changed = () if previous is None else changed_fields(previous, stored.version)
        state = _state(stored, active, current, today)
        history.append(HistoryRow(stored, state, previous, changed))
    return history


def _state(
    stored: StoredSetting,
    active: Sequence[StoredSetting],
    current: SettingVersion | None,
    today: date,
) -> SettingState:
    day = stored.version.effective_from
    if stored.is_cancelled:
        return "cancelled"
    if any(s.id > stored.id and s.version.effective_from == day for s in active):
        return "replaced"
    if day > today:
        return "planned"
    return "in_force" if stored.version is current else "past"


def add_version(
    uow: UnitOfWork,
    toml: PortfolioConfig,
    new: SettingVersion,
    *,
    source: SettingSource,
    today: date,
    at: datetime,
) -> int:
    issues = check_version(
        new, versions=active_versions(uow), classes=toml.targets.keys(), today=today
    )
    if issues:
        raise ConfigError(issues)
    return uow.settings.add(new, source=source, at=at)


def cancel_version(
    uow: UnitOfWork, setting_id: int, *, reason: str, today: date, at: datetime
) -> SettingVersion:
    """Satır silinmez; vazgeçme ve gerekçesi geçmişte kalır."""
    if not reason.strip():
        raise DomainError("Vazgeçme gerekçesi boş olamaz.")
    stored = cancellable(uow, setting_id, today=today)
    uow.settings.cancel(setting_id, reason=reason.strip(), at=at)
    return stored.version


def cancellable(uow: UnitOfWork, setting_id: int, *, today: date) -> StoredSetting:
    """Yalnız yürürlük günü bugünden sonra olan sürümden vazgeçilir."""
    stored = next((s for s in uow.settings.list() if s.id == setting_id), None)
    if stored is None:
        raise DomainError(f"{setting_id} numaralı ayar sürümü yok.")
    if stored.is_cancelled:
        raise DomainError(f"{setting_id} numaralı ayar sürümünden zaten vazgeçilmiş.")
    if stored.version.effective_from <= today:
        raise DomainError(
            f"{setting_id} numaralı ayar sürümü yürürlüğe girmiş; vazgeçilemez. Değiştirmek için"
            " yeni bir sürüm ekle."
        )
    return stored


def toml_warning(current: SettingVersion, toml: PortfolioConfig) -> str | None:
    names = toml_differences(current, toml)
    if not names:
        return None
    listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} ve {names[-1]}"
    return (
        f"portfolio.toml'daki {listed} geçerli ayardan farklı. TOML'daki değer artık"
        " kullanılmıyor; geçerli ayar panelde ya da `ft ayar` ile."
    )


@dataclass(frozen=True, slots=True)
class SettingsSync:
    notes: tuple[str, ...]
    warnings: tuple[str, ...]


def sync_settings(
    uow: UnitOfWork, toml: PortfolioConfig, *, today: date, at: datetime
) -> SettingsSync:
    """`config apply`: sürüm yoksa başlangıç sürümü; sınıf değişikliği bugünkü ve planlanan
    sürümlere yansır; ağırlığı 0 olmayan sınıf silinmişse hiçbir şey yazılmaz (ConfigError)."""
    notes: list[str] = []
    if effective_version(active_versions(uow), today) is None:
        uow.settings.add(start_version(toml), source="toml", at=at)
        notes.append("başlangıç sürümü portfolio.toml'dan yazıldı (yürürlük 0001-01-01).")
    stored = [s for s in uow.settings.list() if not s.is_cancelled]
    changes = class_changes([s.version for s in stored], toml.targets.keys(), today=today)
    if changes.issues:
        raise ConfigError(changes.issues)
    warnings: list[str] = []
    if changes.added or changes.removed:
        notes.extend(_reclass(uow, toml, stored, changes, today=today, at=at))
        warnings.extend(
            f"{name} sınıfının ağırlığı 0; ağırlığını `ft ayar hedef` ya da panelden ver."
            for name in changes.added
        )
    current = effective_version(active_versions(uow), today)
    warning = None if current is None else toml_warning(current, toml)
    if warning is not None:
        warnings.append(warning)
    return SettingsSync(tuple(notes), tuple(warnings))


def _reclass(
    uow: UnitOfWork,
    toml: PortfolioConfig,
    stored: Sequence[StoredSetting],
    changes: ClassChanges,
    *,
    today: date,
    at: datetime,
) -> list[str]:
    classes = set(toml.targets)
    notes: list[str] = []
    current = effective_version([s.version for s in stored], today)
    if current is not None and set(current.targets) != classes:
        moved = with_classes(current, classes, effective_from=today)
        add_version(uow, toml, moved, source="toml", today=today, at=at)
    if changes.added:
        added = ", ".join(changes.added)
        notes.append(f"{added} sınıfı bugünden ({today.isoformat()}) geçerli, 0 ağırlıkla eklendi.")
    if changes.removed:
        notes.append(f"{', '.join(changes.removed)} sınıfı ayarlardan çıkarıldı (ağırlığı 0'dı).")
    parts = [f"eklenen: {', '.join(changes.added)}"] * bool(changes.added)
    parts += [f"çıkarılan: {', '.join(changes.removed)}"] * bool(changes.removed)
    reason = (
        f"portfolio.toml'daki sınıf değişikliği ({'; '.join(parts)}); aynı yürürlük günüyle"
        " yeniden yazıldı."
    )
    for planned in stored:
        day = planned.version.effective_from
        if day <= today or set(planned.version.targets) == classes:
            continue
        uow.settings.cancel(planned.id, reason=reason, at=at)
        rewritten = with_classes(planned.version, classes, effective_from=day)
        add_version(uow, toml, rewritten, source="toml", today=today, at=at)
        notes.append(
            f"yürürlüğü {day.isoformat()} olan planlanan sürüm yeni sınıf listesiyle"
            " yeniden yazıldı."
        )
    return notes
