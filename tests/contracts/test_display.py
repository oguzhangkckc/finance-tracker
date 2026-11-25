from decimal import Decimal

import pytest

from finans.contracts.display import class_label, exact, money, percent, points

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


def test_exact_keeps_every_digit_with_a_decimal_comma() -> None:
    assert exact(D("12.838270")) == "12,83827"
    assert exact(D("4050")) == "4050"
    assert exact(D("0.000001")) == "0,000001"


@pytest.mark.parametrize(
    ("code", "labels", "expected"),
    [
        ("hisse_tr", {"hisse_tr": "Türkiye hisse"}, "Türkiye hisse"),
        ("dusuk_risk", {}, "Dusuk risk"),
        ("istanbul_hisse", {}, "İstanbul hisse"),
        ("ılık_fon", {}, "Ilık fon"),
        ("altin", {"hisse": "Hisse"}, "Altin"),
    ],
)
def test_class_label_prefers_the_configured_name_and_otherwise_turkish_capitalizes(
    code: str, labels: dict[str, str], expected: str
) -> None:
    assert class_label(code, labels) == expected
