from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from finans.domain.models import ZERO, DomainError, Instrument
from finans.domain.numeric import in_domain_context

ONE = Decimal(1)
CLASS_LABEL_MAX = 40


@dataclass(frozen=True, slots=True)
class AlertThresholds:
    open_above: Decimal = Decimal("0.05")
    close_below: Decimal = Decimal("0.03")
    reminder_days: int = 7


# Varsayılan günlük sıçrama eşikleri (K-66); [quality.jump] bunlara eklenir ya da üzerine yazar.
_DEFAULT_JUMP = (("para_piyasasi", Decimal("0.01")), ("default", Decimal("0.10")))


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    jump: Mapping[str, Decimal] = field(default_factory=lambda: dict(_DEFAULT_JUMP))

    @classmethod
    def with_overrides(cls, jump: Mapping[str, Decimal]) -> "QualityThresholds":
        return cls({**dict(_DEFAULT_JUMP), **jump})

    def jump_for(self, instrument: Instrument) -> Decimal:
        for key in (instrument.category, instrument.asset_class):
            if key is not None and key in self.jump:
                return self.jump[key]
        return self.jump["default"]


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    instruments: tuple[Instrument, ...]
    targets: Mapping[str, Decimal]
    monthly_contribution: Decimal | None
    alerts: AlertThresholds
    quality: QualityThresholds = field(default_factory=QualityThresholds)
    payday: int | None = None
    class_labels: Mapping[str, str] = field(default_factory=dict)


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
    allocation: bool = True


def _show(value: Decimal) -> str:
    return "0" if value.is_zero() else format(value.normalize(), "f")


@in_domain_context
def validate_portfolio(
    entries: Sequence[InstrumentEntry],
    targets: Mapping[str, Decimal | None],
    alerts: AlertThresholds | None,
    contribution: Decimal | None,
    *,
    payday: int | None = None,
) -> list[ConfigIssue]:
    """Geçersiz değerli hedefler None olarak gelir; yapısal hatası raporlanmış sayılır."""
    issues: list[ConfigIssue] = []
    if not entries:
        issues.append(ConfigIssue("instruments", "en az bir varlık tanımlanmalı."))
    known = ", ".join(sorted(targets))
    first_seen: dict[str, str] = {}
    for entry in entries:
        in_allocation = entry.allocation and entry.asset_class is not None
        if targets and in_allocation and entry.asset_class not in targets:
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
    if payday is not None and not 1 <= payday <= 31:
        issues.append(
            ConfigIssue("contribution.payday", f"1 ile 31 arasında olmalı; {payday} verildi.")
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
    in_allocation = {entry.asset_class for entry in entries if entry.allocation}
    for name in targets:
        if name not in held:
            issues.append(ConfigIssue(f"targets.{name}", "bu sınıfta tanımlı varlık yok."))
        elif name not in in_allocation:
            message = "bu sınıfta dağılım içi varlık yok; allocation = false olanlar sayılmaz."
            issues.append(ConfigIssue(f"targets.{name}", message))
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


@in_domain_context
def validate_class_labels(labels: Mapping[str, str], classes: Collection[str]) -> list[ConfigIssue]:
    """`[sinif_adlari]` yalnız var olan sınıflara ad verir; sınıf eklemez (K-128)."""
    known = ", ".join(sorted(classes))
    issues: list[ConfigIssue] = []
    for code, label in labels.items():
        path = f"sinif_adlari.{code}"
        if code not in classes:
            issues.append(
                ConfigIssue(path, f'"{code}" bilinen bir sınıf değil. Sınıflar: {known}.')
            )
        elif not label.strip():
            issues.append(ConfigIssue(path, "boş olamaz."))
        elif len(label) > CLASS_LABEL_MAX:
            message = f"en çok {CLASS_LABEL_MAX} karakter olmalı; {len(label)} verildi."
            issues.append(ConfigIssue(path, message))
    return issues


@in_domain_context
def validate_quality(jump: Mapping[str, Decimal | None]) -> list[ConfigIssue]:
    """Değeri ayrıştırılamayan eşik None gelir; yapısal hatası raporlanmış sayılır."""
    return [
        ConfigIssue(
            f"quality.jump.{name}",
            f"0 ile 1 arasında olmalı (0.15 = %15); {_show(value)} verildi.",
        )
        for name, value in jump.items()
        if value is not None and not ZERO < value <= ONE
    ]
