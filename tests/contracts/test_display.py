from decimal import Decimal

import pytest

from finans.contracts.display import money, percent, points

D = Decimal


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (D("1234.565"), "1.234,56 TL"),
        (D("1234.575"), "1.234,58 TL"),
        (D("-1000000"), "-1.000.000,00 TL"),
        (D(0), "0,00 TL"),
        (D("0.5"), "0,50 TL"),
    ],
)
def test_money_uses_turkish_separators_and_banker_rounding(value: Decimal, expected: str) -> None:
    assert money(value) == expected


def test_percent_and_points_show_signs_where_asked() -> None:
    assert percent(D("0.047058")) == "%4,71"
    assert percent(D("0.047058"), signed=True) == "+%4,71"
    assert percent(D("-0.012"), signed=True) == "-%1,20"
    assert percent(D("0.444"), places=1) == "%44,4"
    assert points(D("0.04396")) == "+4,4 puan"
    assert points(D("-0.04396")) == "-4,4 puan"
