from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from finans.domain.models import ZERO, DomainError
from finans.domain.numeric import in_domain_context

Transition = Literal["opened", "resolved"]


@dataclass(frozen=True, slots=True)
class DriftDecision:
    fingerprint: str
    is_open: bool
    transition: Transition | None


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
def evaluate_drift(
    asset_class: str,
    deviation: Decimal,
    *,
    was_open: bool,
    open_above: Decimal,
    close_below: Decimal,
) -> DriftDecision:
    if not ZERO <= close_below < open_above:
        raise DomainError(
            f"Kapanma eşiği ({close_below}) açılma eşiğinin ({open_above}) altında olmalı"
        )
    magnitude = abs(deviation)
    is_open = magnitude >= close_below if was_open else magnitude > open_above
    transition: Transition | None = None
    if is_open and not was_open:
        transition = "opened"
    elif was_open and not is_open:
        transition = "resolved"
    direction = "above" if deviation >= ZERO else "below"
    return DriftDecision(f"drift:{asset_class}:{direction}", is_open, transition)


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
