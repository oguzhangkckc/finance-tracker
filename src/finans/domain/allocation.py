from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Final, Literal

from finans.domain.models import ZERO, DomainError
from finans.domain.numeric import in_domain_context
from finans.domain.portfolio import ONE, AlertThresholds

QUIET_MONTHS: Final = 3
CENT: Final = Decimal("0.01")

Direction = Literal["above", "below"]
EventKind = Literal["opened", "resolved"]


@dataclass(frozen=True, slots=True)
class DriftEvent:
    kind: EventKind
    direction: Direction


@dataclass(frozen=True, slots=True)
class ContributionLine:
    asset_class: str
    instrument: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class DriftDecision:
    fingerprint: str
    open_direction: Direction | None
    events: tuple[DriftEvent, ...]

    @property
    def is_open(self) -> bool:
        return self.open_direction is not None


def _require_non_negative(values: Mapping[str, Decimal], what: str) -> None:
    negative = sorted(name for name, value in values.items() if value < ZERO)
    if negative:
        raise DomainError(f"{what} negatif olamaz: {', '.join(negative)}")


def _require_same_classes(values: Mapping[str, Decimal], targets: Mapping[str, Decimal]) -> None:
    if values.keys() != targets.keys():
        difference = sorted(values.keys() ^ targets.keys())
        raise DomainError(f"Varlık sınıfları hedeflerle uyuşmuyor: {', '.join(difference)}")


@in_domain_context
def weights(values: Mapping[str, Decimal]) -> dict[str, Decimal]:
    _require_non_negative(values, "Sınıf değeri")
    total = sum(values.values(), ZERO)
    if total <= ZERO:
        raise DomainError("Toplam değer sıfır; ağırlık hesaplanamaz")
    return {name: value / total for name, value in values.items()}


@in_domain_context
def validate_targets(targets: Mapping[str, Decimal]) -> None:
    if not targets:
        raise DomainError("Hedef dağılım boş")
    _require_non_negative(targets, "Hedef ağırlık")
    total = sum(targets.values(), ZERO)
    if total != 1:
        raise DomainError(f"Hedef ağırlıkların toplamı 1 olmalı: {total}")


@in_domain_context
def deviations(
    current: Mapping[str, Decimal], targets: Mapping[str, Decimal]
) -> dict[str, Decimal]:
    validate_targets(targets)
    _require_same_classes(current, targets)
    return {name: current[name] - targets[name] for name in targets}


@in_domain_context
def drift_fingerprint(asset_class: str) -> str:
    return f"drift:{asset_class}"


@in_domain_context
def evaluate_drift(
    asset_class: str,
    deviation: Decimal,
    *,
    open_direction: Direction | None,
    open_above: Decimal,
    close_below: Decimal,
) -> DriftDecision:
    if not ZERO <= close_below < open_above:
        raise DomainError(
            f"Kapanma eşiği ({close_below}) açılma eşiğinin ({open_above}) altında olmalı"
        )
    magnitude = abs(deviation)
    events: list[DriftEvent] = []
    current = open_direction
    if current is not None:
        crossed = deviation < ZERO if current == "above" else deviation > ZERO
        if crossed or magnitude < close_below:
            events.append(DriftEvent("resolved", current))
            current = None
    if current is None and magnitude > open_above:
        current = "above" if deviation > ZERO else "below"
        events.append(DriftEvent("opened", current))
    return DriftDecision(drift_fingerprint(asset_class), current, tuple(events))


@in_domain_context
def should_notify(last_sent: date | None, today: date, *, cooldown_days: int) -> bool:
    return last_sent is None or (today - last_sent).days >= cooldown_days


@in_domain_context
def allocate_contribution(
    values: Mapping[str, Decimal], targets: Mapping[str, Decimal], contribution: Decimal
) -> dict[str, Decimal]:
    validate_targets(targets)
    _require_same_classes(values, targets)
    _require_non_negative(values, "Sınıf değeri")
    if contribution < ZERO:
        raise DomainError(f"Katkı negatif olamaz: {contribution}")
    if contribution == ZERO:
        return dict.fromkeys(targets, ZERO)
    total = sum(values.values(), ZERO) + contribution
    gaps = {name: max(ZERO, targets[name] * total - values[name]) for name in targets}
    gap_sum = sum(gaps.values(), ZERO)
    return {name: contribution * gap / gap_sum for name, gap in gaps.items()}


@in_domain_context
def quiet_threshold(contribution: Decimal | None) -> Decimal:
    return ZERO if contribution is None else contribution * QUIET_MONTHS


@in_domain_context
def quiet_period_over(
    value: Decimal, contribution: Decimal | None, *, ended_on: date | None
) -> bool:
    """Sessiz dönem bir kez biter ve geri dönmez (K-75)."""
    return ended_on is not None or value >= quiet_threshold(contribution)


@in_domain_context
def evaluate_portfolio_drift(
    values: Mapping[str, Decimal],
    targets: Mapping[str, Decimal],
    open_directions: Mapping[str, Direction],
    thresholds: AlertThresholds,
) -> list[DriftDecision]:
    current = deviations(weights(values), targets)
    return [
        evaluate_drift(
            name,
            current[name],
            open_direction=open_directions.get(name),
            open_above=thresholds.open_above,
            close_below=thresholds.close_below,
        )
        for name in sorted(targets)
    ]


@in_domain_context
def round_to_cents(amounts: Mapping[str, Decimal], total: Decimal) -> dict[str, Decimal]:
    """En büyük kalan (Hamilton) yöntemi; eşit kalanlarda ad sırası (K-37)."""
    _require_non_negative(amounts, "Tutar")
    if total != total.quantize(CENT):
        raise DomainError(f"Toplam kuruşa tam olmalı: {total}")
    if abs(sum(amounts.values(), ZERO) - total) >= CENT:
        raise DomainError(f"Tutarların toplamı {total} ile tutmuyor")
    floors = {name: amount.quantize(CENT, rounding=ROUND_FLOOR) for name, amount in amounts.items()}
    missing = int((total - sum(floors.values(), ZERO)) / CENT)
    winners = set(sorted(amounts, key=lambda name: (floors[name] - amounts[name], name))[:missing])
    return {name: floors[name] + (CENT if name in winners else ZERO) for name in sorted(amounts)}


@in_domain_context
def plan_contribution(
    funds: Mapping[str, Mapping[str, Decimal]],
    targets: Mapping[str, Decimal],
    contribution: Decimal,
) -> list[ContributionLine]:
    """Sınıf payı fonlara değerleriyle orantılı, sınıf değeri 0 ise eşit bölünür (K-83)."""
    empty = sorted(name for name, members in funds.items() if not members)
    if empty:
        raise DomainError(f"Dağılım içi fonu olmayan sınıf: {', '.join(empty)}")
    class_values = {name: sum(members.values(), ZERO) for name, members in funds.items()}
    shares = allocate_contribution(class_values, targets, contribution)
    exact: dict[str, Decimal] = {}
    owner: dict[str, str] = {}
    for name, members in funds.items():
        total = class_values[name]
        for code, value in members.items():
            exact[code] = shares[name] * (value / total if total > ZERO else ONE / len(members))
            owner[code] = name
    rounded = round_to_cents(exact, contribution)
    ordered = sorted(exact, key=lambda code: (owner[code], code))
    return [ContributionLine(owner[code], code, rounded[code]) for code in ordered]
