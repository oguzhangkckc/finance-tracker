from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finans.domain.allocation import (
    DriftDecision,
    allocate_contribution,
    deviations,
    evaluate_drift,
    should_notify,
    validate_targets,
    weights,
)
from finans.domain.models import DomainError
from tests.support.decimals import is_close

D = Decimal
TARGETS = {"hisse": D("0.6"), "dusuk_risk": D("0.3"), "altin": D("0.1")}
OPEN_ABOVE = D("0.05")
CLOSE_BELOW = D("0.03")
EXACT = D("1e-20")


class TestWeights:
    def test_example(self) -> None:
        assert weights({"a": D(30), "b": D(70)}) == {"a": D("0.3"), "b": D("0.7")}

    @pytest.mark.parametrize("values", [{"a": D(0)}, {"a": D(5), "b": D(-1)}])
    def test_rejects_zero_total_and_negative_values(self, values: dict[str, Decimal]) -> None:
        with pytest.raises(DomainError):
            weights(values)

    @given(
        st.dictionaries(
            st.sampled_from(["a", "b", "c", "d", "e"]),
            st.decimals(min_value=D("0.01"), max_value=D("1e9"), places=2),
            min_size=1,
        )
    )
    def test_weights_sum_to_one(self, values: dict[str, Decimal]) -> None:
        assert is_close(sum(weights(values).values(), D(0)), D(1), rel_tol=EXACT, abs_tol=EXACT)


class TestTargetsAndDeviations:
    def test_valid_targets_pass(self) -> None:
        validate_targets(TARGETS)

    @pytest.mark.parametrize(
        "targets",
        [{"a": D("0.5"), "b": D("0.4")}, {"a": D("1.1"), "b": D("-0.1")}, {}],
    )
    def test_invalid_targets_are_rejected(self, targets: dict[str, Decimal]) -> None:
        with pytest.raises(DomainError):
            validate_targets(targets)

    def test_deviation_is_weight_minus_target(self) -> None:
        current = {"hisse": D("0.7"), "dusuk_risk": D("0.25"), "altin": D("0.05")}
        assert deviations(current, TARGETS) == {
            "hisse": D("0.1"),
            "dusuk_risk": D("-0.05"),
            "altin": D("-0.05"),
        }

    def test_class_sets_must_match(self) -> None:
        with pytest.raises(DomainError, match="altin"):
            deviations({"hisse": D("0.7"), "dusuk_risk": D("0.3")}, TARGETS)


def _drift(deviation: str, *, was_open: bool) -> DriftDecision:
    return evaluate_drift(
        "hisse", D(deviation), was_open=was_open, open_above=OPEN_ABOVE, close_below=CLOSE_BELOW
    )


class TestHysteresis:
    @pytest.mark.parametrize(
        ("deviation", "was_open", "is_open", "transition", "direction"),
        [
            ("0.0501", False, True, "opened", "above"),
            ("0.05", False, False, None, "above"),
            ("0.04", True, True, None, "above"),
            ("0.03", True, True, None, "above"),
            ("0.0299", True, False, "resolved", "above"),
            ("0.02", False, False, None, "above"),
            ("-0.0501", False, True, "opened", "below"),
            ("-0.05", False, False, None, "below"),
            ("-0.03", True, True, None, "below"),
            ("-0.0299", True, False, "resolved", "below"),
        ],
    )
    def test_thresholds(
        self,
        deviation: str,
        was_open: bool,
        is_open: bool,
        transition: str | None,
        direction: str,
    ) -> None:
        assert _drift(deviation, was_open=was_open) == DriftDecision(
            f"drift:hisse:{direction}",
            is_open,
            transition,  # type: ignore[arg-type]
        )

    def test_close_threshold_must_be_below_open_threshold(self) -> None:
        with pytest.raises(DomainError):
            evaluate_drift(
                "hisse", D("0.1"), was_open=False, open_above=D("0.03"), close_below=D("0.05")
            )

    @given(
        st.booleans(),
        st.lists(st.decimals(min_value=CLOSE_BELOW, max_value=OPEN_ABOVE, places=6), min_size=1),
        st.booleans(),
    )
    def test_no_flapping_inside_the_band(
        self, was_open: bool, magnitudes: list[Decimal], negative: bool
    ) -> None:
        state = was_open
        for magnitude in magnitudes:
            decision = evaluate_drift(
                "hisse",
                -magnitude if negative else magnitude,
                was_open=state,
                open_above=OPEN_ABOVE,
                close_below=CLOSE_BELOW,
            )
            assert decision.transition is None
            state = decision.is_open
        assert state is was_open


@pytest.mark.parametrize(
    ("last_sent", "expected"),
    [(None, True), (date(2026, 3, 10), False), (date(2026, 3, 4), False), (date(2026, 3, 3), True)],
)
def test_cooldown(last_sent: date | None, expected: bool) -> None:
    assert should_notify(last_sent, date(2026, 3, 10), cooldown_days=7) is expected


class TestAllocateContribution:
    def test_without_overweight_class_each_gap_is_filled_exactly(self) -> None:
        values = {"hisse": D(500), "dusuk_risk": D(400), "altin": D(100)}
        assert allocate_contribution(values, TARGETS, D(1000)) == {
            "hisse": D(700),
            "dusuk_risk": D(200),
            "altin": D(100),
        }

    def test_overweight_class_gets_nothing_and_gaps_share_the_contribution(self) -> None:
        values = {"hisse": D(2500), "dusuk_risk": D(300), "altin": D(200)}
        allocation = allocate_contribution(values, TARGETS, D(1000))
        assert allocation["hisse"] == D(0)
        assert is_close(allocation["dusuk_risk"], D(1000) * D(900) / D(1100))
        assert is_close(allocation["altin"], D(1000) * D(200) / D(1100))

    def test_zero_contribution_allocates_nothing(self) -> None:
        values = {"hisse": D(2500), "dusuk_risk": D(300), "altin": D(200)}
        assert allocate_contribution(values, TARGETS, D(0)) == dict.fromkeys(TARGETS, D(0))

    def test_empty_portfolio_follows_targets(self) -> None:
        values = dict.fromkeys(TARGETS, D(0))
        assert allocate_contribution(values, TARGETS, D(1000)) == {
            "hisse": D(600),
            "dusuk_risk": D(300),
            "altin": D(100),
        }

    @pytest.mark.parametrize(
        ("values", "contribution"),
        [
            ({"hisse": D(1), "dusuk_risk": D(1), "altin": D(1)}, D(-1)),
            ({"hisse": D(1), "dusuk_risk": D(1)}, D(1)),
        ],
    )
    def test_invalid_input_is_rejected(
        self, values: dict[str, Decimal], contribution: Decimal
    ) -> None:
        with pytest.raises(DomainError):
            allocate_contribution(values, TARGETS, contribution)


@st.composite
def portfolios(
    draw: st.DrawFn,
) -> tuple[dict[str, Decimal], dict[str, Decimal], Decimal]:
    count = draw(st.integers(min_value=1, max_value=5))
    cuts = sorted(draw(st.lists(st.integers(0, 100), min_size=count - 1, max_size=count - 1)))
    shares = [b - a for a, b in zip([0, *cuts], [*cuts, 100], strict=True)]
    classes = [f"c{i}" for i in range(count)]
    targets = {c: D(share) / D(100) for c, share in zip(classes, shares, strict=True)}
    money = st.decimals(min_value=D(0), max_value=D("1e9"), places=2)
    values = {c: draw(money) for c in classes}
    contribution = draw(st.decimals(min_value=D("0.01"), max_value=D("1e7"), places=2))
    return values, targets, contribution


@given(portfolios())
def test_allocation_properties(
    portfolio: tuple[dict[str, Decimal], dict[str, Decimal], Decimal],
) -> None:
    values, targets, contribution = portfolio
    allocation = allocate_contribution(values, targets, contribution)
    total = sum(values.values(), D(0)) + contribution

    assert is_close(sum(allocation.values(), D(0)), contribution, rel_tol=EXACT, abs_tol=EXACT)
    for asset_class, amount in allocation.items():
        target = targets[asset_class] * total
        gap = max(D(0), target - values[asset_class])
        assert amount >= 0
        assert amount <= gap or is_close(amount, gap, rel_tol=EXACT, abs_tol=EXACT)
        if gap > 0:
            reached = values[asset_class] + amount
            assert reached <= target or is_close(reached, target, rel_tol=EXACT, abs_tol=EXACT)
        else:
            assert amount == 0
