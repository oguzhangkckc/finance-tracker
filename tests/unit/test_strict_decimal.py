from decimal import Decimal, FloatOperation

import pytest


def test_decimal_from_float_is_trapped_in_tests() -> None:
    with pytest.raises(FloatOperation):
        Decimal(0.1)  # noqa: RUF032


def test_ordering_decimal_against_float_is_trapped_in_tests() -> None:
    with pytest.raises(FloatOperation):
        _ = Decimal("1") < 1.5
