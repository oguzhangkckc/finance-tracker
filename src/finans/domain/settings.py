"""Yürürlük tarihli ayarlar (K-127): maaş günü, aylık katkı ve hedef dağılım. Bir günün ayarı, o
güne kadar yürürlüğe girmiş son sürümdür; her sürüm üç ayarı birden taşır."""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finans.domain.models import ZERO, YearMonth
from finans.domain.numeric import canonical_text, in_domain_context
from finans.domain.portfolio import ONE, ConfigIssue


@dataclass(frozen=True, slots=True)
class SettingVersion:
    effective_from: date
    payday: int | None
    monthly_contribution: Decimal | None
    targets: Mapping[str, Decimal]


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
