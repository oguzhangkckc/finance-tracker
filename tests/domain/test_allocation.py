from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finans.domain.allocation import (
    Direction,
    DriftDecision,
    DriftEvent,
    allocate_contribution,
    deviations,
    drift_fingerprint,
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


def _drift(deviation: Decimal | str, open_direction: Direction | None) -> DriftDecision:
    return evaluate_drift(
        "hisse",
        D(deviation),
        open_direction=open_direction,
        open_above=OPEN_ABOVE,
        close_below=CLOSE_BELOW,
    )


OPENED_ABOVE = DriftEvent("opened", "above")
OPENED_BELOW = DriftEvent("opened", "below")
RESOLVED_ABOVE = DriftEvent("resolved", "above")
RESOLVED_BELOW = DriftEvent("resolved", "below")


class TestHysteresis:
    @pytest.mark.parametrize(
        ("deviation", "open_before", "open_after", "events"),
        [
            ("0.0501", None, "above", (OPENED_ABOVE,)),
            ("0.05", None, None, ()),
            ("0.04", "above", "above", ()),
            ("0.03", "above", "above", ()),
            ("0.0299", "above", None, (RESOLVED_ABOVE,)),
            ("0.02", None, None, ()),
            ("-0.0501", None, "below", (OPENED_BELOW,)),
            ("-0.05", None, None, ()),
            ("-0.03", "below", "below", ()),
            ("-0.0299", "below", None, (RESOLVED_BELOW,)),
            ("0", "above", None, (RESOLVED_ABOVE,)),
        ],
    )
    def test_thresholds(
        self,
        deviation: str,
        open_before: Direction | None,
        open_after: Direction | None,
        events: tuple[DriftEvent, ...],
    ) -> None:
        assert _drift(deviation, open_before) == DriftDecision("drift:hisse", open_after, events)

    def test_sign_change_within_open_threshold_only_resolves(self) -> None:
        decision = _drift("-0.04", "above")
        assert decision.events == (RESOLVED_ABOVE,)
        assert not decision.is_open

    @pytest.mark.parametrize(
        ("deviation", "open_before", "events", "open_after"),
        [
            ("-0.06", "above", (RESOLVED_ABOVE, OPENED_BELOW), "below"),
            ("0.06", "below", (RESOLVED_BELOW, OPENED_ABOVE), "above"),
        ],
    )
    def test_sign_change_beyond_open_threshold_resolves_and_reopens(
        self,
        deviation: str,
        open_before: Direction,
        events: tuple[DriftEvent, ...],
        open_after: Direction,
    ) -> None:
        decision = _drift(deviation, open_before)
        assert decision.events == events
        assert decision.open_direction == open_after

    def test_fingerprint_is_one_per_class_regardless_of_direction(self) -> None:
        decisions = [_drift("0.06", None), _drift("-0.06", None), _drift("-0.06", "above")]
        assert {d.fingerprint for d in decisions} == {drift_fingerprint("hisse")} == {"drift:hisse"}

    def test_close_threshold_must_be_below_open_threshold(self) -> None:
        with pytest.raises(DomainError):
            evaluate_drift(
                "hisse", D("0.1"), open_direction=None, open_above=D("0.03"), close_below=D("0.05")
            )

    @given(
        st.lists(st.decimals(min_value=CLOSE_BELOW, max_value=OPEN_ABOVE, places=6), min_size=1),
        st.booleans(),
        st.booleans(),
    )
    def test_no_flapping_inside_the_band(
        self, magnitudes: list[Decimal], negative: bool, starts_open: bool
    ) -> None:
        side: Direction = "below" if negative else "above"
        state: Direction | None = side if starts_open else None
        for magnitude in magnitudes:
            decision = _drift(-magnitude if negative else magnitude, state)
            assert decision.events == ()
            state = decision.open_direction
        assert state == (side if starts_open else None)

    @given(st.lists(st.decimals(min_value=D("-0.2"), max_value=D("0.2"), places=4), max_size=60))
    def test_at_most_one_open_alarm_and_every_opening_is_resolved(
        self, deviations_: list[Decimal]
    ) -> None:
        state: Direction | None = None
        opened = resolved = 0
        for deviation in [*deviations_, D(0)]:
            decision = _drift(deviation, state)
            replay = state
            for event in decision.events:
                if event.kind == "resolved":
                    assert replay == event.direction
                    replay = None
                    resolved += 1
                else:
                    assert replay is None
                    replay = event.direction
                    opened += 1
            assert replay == decision.open_direction
            state = decision.open_direction
        assert state is None
        assert opened == resolved


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
