from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from finans.domain.models import ZERO, DomainError, Instrument
from finans.domain.numeric import in_domain_context

ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class AlertThresholds:
    open_above: Decimal = Decimal("0.05")
    close_below: Decimal = Decimal("0.03")
    reminder_days: int = 7


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    instruments: tuple[Instrument, ...]
    targets: Mapping[str, Decimal]
    monthly_contribution: Decimal
    alerts: AlertThresholds


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class ConfigError(DomainError):
    def __init__(self, issues: Sequence[ConfigIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("\n".join(str(issue) for issue in self.issues))


@dataclass(frozen=True, slots=True)
class InstrumentEntry:
    """Dosyadaki bir varlık satırı; ayrıştırılamayan alanlar None'dır."""

    path: str
    code: str | None
    asset_class: str | None


def _show(value: Decimal) -> str:
    return "0" if value.is_zero() else format(value.normalize(), "f")


@in_domain_context
def validate_portfolio(
    entries: Sequence[InstrumentEntry],
    targets: Mapping[str, Decimal | None],
    alerts: AlertThresholds | None,
    contribution: Decimal | None,
) -> list[ConfigIssue]:
    """Geçersiz değerli hedefler None olarak gelir; yapısal hatası raporlanmış sayılır."""
    issues: list[ConfigIssue] = []
    if not entries:
        issues.append(ConfigIssue("instruments", "en az bir varlık tanımlanmalı."))
    known = ", ".join(sorted(targets))
    first_seen: dict[str, str] = {}
    for entry in entries:
        if targets and entry.asset_class is not None and entry.asset_class not in targets:
            issues.append(
                ConfigIssue(
                    f"{entry.path}.asset_class",
                    f'"{entry.asset_class}" hedeflerde yok. Hedef sınıflar: {known}.',
                )
            )
        if entry.code is None:
            continue
        if entry.code in first_seen:
            issues.append(
                ConfigIssue(
                    f"{entry.path}.code",
                    f'"{entry.code}" iki kez tanımlı (ilki {first_seen[entry.code]}).',
                )
            )
        else:
            first_seen[entry.code] = entry.path
    issues.extend(_target_issues(entries, targets))
    issues.extend(_alert_issues(alerts))
    if contribution is not None and contribution < ZERO:
        issues.append(
            ConfigIssue("contribution.monthly", f"negatif olamaz; {_show(contribution)} verildi.")
        )
    return issues


def _target_issues(
    entries: Sequence[InstrumentEntry], targets: Mapping[str, Decimal | None]
) -> list[ConfigIssue]:
    if not targets:
        return [ConfigIssue("targets", "en az bir hedef sınıf tanımlanmalı.")]
    issues = [
        ConfigIssue(f"targets.{name}", f"negatif olamaz; {_show(value)} verildi.")
        for name, value in targets.items()
        if value is not None and value < ZERO
    ]
    held = {entry.asset_class for entry in entries if entry.asset_class is not None}
    issues.extend(
        ConfigIssue(f"targets.{name}", "bu sınıfta tanımlı varlık yok.")
        for name in targets
        if name not in held
    )
    valid = {name: value for name, value in targets.items() if value is not None}
    if len(valid) == len(targets):
        issues.extend(_sum_issue(valid))
    return issues


def _sum_issue(targets: Mapping[str, Decimal]) -> list[ConfigIssue]:
    total = sum(targets.values(), ZERO)
    if total == ONE:
        return []
    gap = ONE - total
    word = "eksik" if gap > ZERO else "fazla"
    message = f"ağırlıkların toplamı 1 olmalı, şu an {_show(total)} ({word} {_show(abs(gap))})."
    last_name, last_value = list(targets.items())[-1]
    fixed = last_value + gap
    if fixed >= ZERO:
        shown = [_show(value) for value in list(targets.values())[:-1]] + [_show(fixed)]
        message += (
            f" Örneğin {last_name} değerini {_show(last_value)} yerine {_show(fixed)} yaparsan"
            f" toplam tam 1 olur ({' + '.join(shown)})."
        )
    return [ConfigIssue("targets", message)]


def _alert_issues(alerts: AlertThresholds | None) -> list[ConfigIssue]:
    if alerts is None:
        return []
    issues: list[ConfigIssue] = []
    if not alerts.close_below < alerts.open_above:
        issues.append(
            ConfigIssue(
                "alerts",
                f"close_below ({_show(alerts.close_below)}), open_above "
                f"({_show(alerts.open_above)}) değerinden küçük olmalı.",
            )
        )
    elif not (alerts.close_below >= ZERO and alerts.open_above <= ONE):
        issues.append(ConfigIssue("alerts", "eşikler 0 ile 1 arasında olmalı."))
    if alerts.reminder_days < 1:
        issues.append(
            ConfigIssue("alerts.reminder_days", f"en az 1 olmalı; {alerts.reminder_days} verildi.")
        )
    return issues
