"""Yürürlük tarihli ayarlar (K-127). Sürüm yoksa portfolio.toml geçerlidir; ilk `config apply`
başlangıç sürümünü yazana kadar davranış değişmez. Her okuyucu ilgili günün sürümünü kullanır:
rapor mantıksal gününü, maaş günü planı maaş gününü, alarm değerlendirildiği günü."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum
from typing import Final

from finans.domain.models import DomainError, YearMonth
from finans.domain.portfolio import ConfigError, PortfolioConfig
from finans.domain.settings import (
    ClassChanges,
    SettingVersion,
    check_version,
    class_changes,
    effective_version,
    payday_schedule,
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


def payday_for(uow: UnitOfWork, toml: PortfolioConfig) -> Callable[[YearMonth], int | None]:
    """Her ayın maaş günü o ayın 1'indeki sürümden; maaş günü işinin mantıksal günü buna göre."""
    return payday_schedule(active_versions(uow), fallback=toml.payday)


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
    """Yalnız yürürlük günü bugünden sonra olan sürümden vazgeçilir; satır silinmez."""
    if not reason.strip():
        raise DomainError("Vazgeçme gerekçesi boş olamaz.")
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
    uow.settings.cancel(setting_id, reason=reason.strip(), at=at)
    return stored.version


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
