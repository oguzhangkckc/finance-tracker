from decimal import (
    ROUND_HALF_EVEN,
    Decimal,
    DivisionByZero,
    FloatOperation,
    getcontext,
    localcontext,
)

import pytest

from finans.domain.numeric import DOMAIN_CONTEXT, in_domain_context


@in_domain_context
def _third() -> Decimal:
    """Bir bölü üç."""
    return Decimal(1) / Decimal(3)


@in_domain_context
def _from_float(value: float) -> Decimal:
    return Decimal(value)


@in_domain_context
def _divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    return numerator / denominator


def test_domain_context_settings() -> None:
    assert DOMAIN_CONTEXT.prec == 28
    assert DOMAIN_CONTEXT.rounding == ROUND_HALF_EVEN
    assert _third() == Decimal("0.3333333333333333333333333333")


def test_float_is_trapped_in_domain_even_if_global_context_allows_it() -> None:
    with localcontext() as context:
        context.traps[FloatOperation] = False
        with pytest.raises(FloatOperation):
            _from_float(0.1)


def test_division_by_zero_is_trapped() -> None:
    with pytest.raises(DivisionByZero):
        _divide(Decimal(1), Decimal(0))


def test_global_precision_does_not_affect_domain_and_is_restored() -> None:
    with localcontext() as context:
        context.prec = 5
        assert _third() == Decimal("0.3333333333333333333333333333")
        assert getcontext().prec == 5


def test_wrapper_keeps_function_metadata() -> None:
    assert _third.__name__ == "_third"
    assert _third.__doc__ == "Bir bölü üç."
