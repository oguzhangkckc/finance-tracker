"""Yürürlük tarihli ayarlar (K-127): maaş günü, aylık katkı ve hedef dağılım. Bir günün ayarı, o
güne kadar yürürlüğe girmiş son sürümdür; her sürüm üç ayarı birden taşır."""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Final, Literal, Protocol

from finans.domain.models import ZERO, DomainError, YearMonth
from finans.domain.numeric import canonical_text, in_domain_context
from finans.domain.portfolio import ONE, ConfigIssue, PortfolioConfig

SettingField = Literal["payday", "monthly_contribution", "targets"]
FIELDS: Final[tuple[SettingField, ...]] = ("payday", "monthly_contribution", "targets")
FIELD_LABELS: Final[Mapping[SettingField, str]] = {
    "payday": "maaş günü",
    "monthly_contribution": "aylık katkı",
    "targets": "hedefler",
}


class SettingValues(Protocol):
    """Sürüm ve portfolio.toml aynı üç ayarı taşır."""

    @property
    def payday(self) -> int | None: ...
    @property
    def monthly_contribution(self) -> Decimal | None: ...
    @property
    def targets(self) -> Mapping[str, Decimal]: ...


@dataclass(frozen=True, slots=True)
class SettingVersion:
    effective_from: date
    payday: int | None
    monthly_contribution: Decimal | None
    targets: Mapping[str, Decimal]


@dataclass(frozen=True, slots=True)
class ClassChanges:
    """portfolio.toml'un sınıfları ile bugünkü ve planlanan sürümlerinkinin farkı. `blocked`:
    silinmiş ama bir sürümde ağırlığı 0 olmayan sınıflar; `issues` bunların gerekçesidir."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    blocked: tuple[str, ...]
    issues: tuple[ConfigIssue, ...]


@in_domain_context
def start_version(config: PortfolioConfig) -> SettingVersion:
    """İlk `config apply`: portfolio.toml'daki değerler `0001-01-01`'den geçerli."""
    return SettingVersion(
        date.min, config.payday, config.monthly_contribution, dict(config.targets)
    )


@in_domain_context
def effective_version(versions: Iterable[SettingVersion], on: date) -> SettingVersion | None:
    """`versions` kayıt sırasıyla gelir; aynı yürürlük gününde sonra kaydedilen kazanır."""
    chosen: SettingVersion | None = None
    for version in versions:
        if version.effective_from <= on and (
            chosen is None or version.effective_from >= chosen.effective_from
        ):
            chosen = version
    return chosen


@in_domain_context
def check_version(
    new: SettingVersion,
    *,
    versions: Sequence[SettingVersion],
    classes: Collection[str],
    today: date,
) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    if new.effective_from < today:
        issues.append(
            ConfigIssue(
                "effective_from",
                f"yürürlük günü en erken bugün ({today.isoformat()}) olabilir.",
            )
        )
    in_force = effective_version(versions, new.effective_from)
    # K-127: ay içinde maaş günü değişirse o ay iki maaş günü ya da hiç maaş günü olabilirdi.
    if in_force is not None and new.payday != in_force.payday and new.effective_from.day != 1:
        issues.append(
            ConfigIssue(
                "effective_from", "maaş günü değişikliği yalnız bir ayın 1'inden geçerli olabilir."
            )
        )
    if new.payday is not None and not 1 <= new.payday <= 31:
        issues.append(ConfigIssue("payday", f"1 ile 31 arasında olmalı; {new.payday} verildi."))
    if new.monthly_contribution is not None and new.monthly_contribution < ZERO:
        shown = canonical_text(new.monthly_contribution)
        issues.append(ConfigIssue("monthly_contribution", f"negatif olamaz; {shown} verildi."))
    issues.extend(_target_issues(new.targets, classes))
    return issues


def _target_issues(targets: Mapping[str, Decimal], classes: Collection[str]) -> list[ConfigIssue]:
    missing, extra = sorted(set(classes) - set(targets)), sorted(set(targets) - set(classes))
    if missing or extra:
        parts = [f"eksik: {', '.join(missing)}"] * bool(missing)
        parts += [f"fazla: {', '.join(extra)}"] * bool(extra)
        message = f"sınıflar portfolio.toml'dakiyle aynı olmalı; {'; '.join(parts)}."
        return [ConfigIssue("targets", message)]
    issues = [
        ConfigIssue(f"targets.{name}", f"0 ile 1 arasında olmalı; {canonical_text(value)} verildi.")
        for name, value in targets.items()
        if not ZERO <= value <= ONE
    ]
    total = sum(targets.values(), ZERO)
    if not issues and total != ONE:
        message = f"hedeflerin toplamı tam 1 olmalı, şu an {canonical_text(total)}."
        issues.append(ConfigIssue("targets", message))
    return issues


@in_domain_context
def payday_schedule(
    versions: Sequence[SettingVersion], *, fallback: int | None
) -> Callable[[YearMonth], int | None]:
    """Her ayın maaş günü o ayın 1'inde yürürlükte olan sürümden; sürüm yoksa `fallback`."""

    def payday(month: YearMonth) -> int | None:
        version = effective_version(versions, date(month.year, month.month, 1))
        return fallback if version is None else version.payday

    return payday


@in_domain_context
def class_changes(
    versions: Sequence[SettingVersion], classes: Collection[str], *, today: date
) -> ClassChanges:
    wanted = set(classes)
    relevant = _in_force_and_planned(versions, today)
    added = {name for version in relevant for name in wanted - set(version.targets)}
    removed = {name for version in relevant for name in set(version.targets) - wanted}
    issues = [issue for version in relevant for issue in _removal_issues(version, wanted, today)]
    blocked = {
        name
        for version in relevant
        for name, weight in version.targets.items()
        if name not in wanted and weight != ZERO
    }
    return ClassChanges(
        tuple(sorted(added)), tuple(sorted(removed)), tuple(sorted(blocked)), tuple(issues)
    )


def _in_force_and_planned(versions: Sequence[SettingVersion], today: date) -> list[SettingVersion]:
    """Yerini başka sürüme bırakmış eski sürümler geçmiştir; yalnız eski raporları üretir."""
    current = effective_version(versions, today)
    planned = [version for version in versions if version.effective_from > today]
    return ([] if current is None else [current]) + planned


def _removal_issues(version: SettingVersion, wanted: set[str], today: date) -> list[ConfigIssue]:
    if version.effective_from <= today:
        where = "geçerli ayardaki"
        advice = (
            "Önce ağırlığını 0 yap: sınıfı portfolio.toml'a geri ekle, `ft ayar hedef` ile 0 yap,"
            " sonra sil."
        )
    else:
        where = f"yürürlüğü {version.effective_from.isoformat()} olan planlanan sürümdeki"
        advice = "Önce ağırlığını 0 yap ya da o sürümden `ft ayar vazgec` ile vazgeç."
    return [
        ConfigIssue(
            f"targets.{name}",
            f"portfolio.toml'dan silinmiş ama {where} ağırlığı {canonical_text(weight)}. {advice}",
        )
        for name, weight in version.targets.items()
        if name not in wanted and weight != ZERO
    ]


@in_domain_context
def with_classes(
    version: SettingVersion, classes: Collection[str], *, effective_from: date
) -> SettingVersion:
    """Yeni sınıf 0 ağırlıkla girer, listede olmayan çıkar; ağırlığı olan sınıf çıkarılmaz."""
    wanted = set(classes)
    weighted = sorted(
        name for name, weight in version.targets.items() if name not in wanted and weight != ZERO
    )
    if weighted:
        raise DomainError(f"ağırlığı 0 olmayan sınıf çıkarılamaz: {', '.join(weighted)}")
    kept = {name: weight for name, weight in version.targets.items() if name in wanted}
    added = dict.fromkeys(sorted(wanted - kept.keys()), ZERO)
    return replace(version, effective_from=effective_from, targets={**kept, **added})


@in_domain_context
def changed_fields(old: SettingValues, new: SettingValues) -> tuple[SettingField, ...]:
    same: dict[SettingField, bool] = {
        "payday": old.payday == new.payday,
        "monthly_contribution": old.monthly_contribution == new.monthly_contribution,
        "targets": dict(old.targets) == dict(new.targets),
    }
    return tuple(field for field in FIELDS if not same[field])


@dataclass(frozen=True, slots=True)
class Revert:
    """İleri tarihli bir sürüm değişen ayarı hâlâ eski değeriyle taşıyor; o günden itibaren
    değişiklik geri alınmış olur. `index` sürüm listesindeki sırası, `carried` yalnız `fields`
    güncellenmiş hâlidir."""

    index: int
    fields: tuple[SettingField, ...]
    carried: SettingVersion


@in_domain_context
def reverting_versions(
    new: SettingVersion,
    base: SettingVersion,
    versions: Sequence[SettingVersion],
    fields: Collection[SettingField],
) -> list[Revert]:
    """`base`: yeni sürümün yerine geçtiği, o gün geçerli sürüm. Her ayar için ileri tarihli
    sürümlere tarih sırasıyla bakılır; ayarı bilerek başka değere çekmiş ilk sürümde durulur,
    onun ve sonrakilerin değeri korunur. Aynı gün sonra kaydedilenle değişmiş sürüm sayılmaz."""
    later = sorted(
        (
            index
            for index, version in enumerate(versions)
            if version.effective_from > new.effective_from
            and not any(v.effective_from == version.effective_from for v in versions[index + 1 :])
        ),
        key=lambda index: versions[index].effective_from,
    )
    stale: dict[int, set[SettingField]] = {}
    for field in fields:
        for index in later:
            if field in changed_fields(versions[index], base):
                break
            stale.setdefault(index, set()).add(field)
    return [
        Revert(
            index,
            tuple(field for field in FIELDS if field in reverted),
            _carry(versions[index], new, reverted),
        )
        for index, reverted in sorted(stale.items())
    ]


def _carry(
    version: SettingVersion, new: SettingVersion, fields: Collection[SettingField]
) -> SettingVersion:
    return replace(
        version,
        payday=new.payday if "payday" in fields else version.payday,
        monthly_contribution=(
            new.monthly_contribution
            if "monthly_contribution" in fields
            else version.monthly_contribution
        ),
        targets=dict(new.targets) if "targets" in fields else version.targets,
    )


@in_domain_context
def toml_differences(version: SettingVersion, config: PortfolioConfig) -> list[str]:
    """Başlangıçtan sonra TOML'daki değer kullanılmaz; farklı olan ayarın yalnız adı verilir."""
    return [FIELD_LABELS[field] for field in changed_fields(version, config)]
