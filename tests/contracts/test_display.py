from datetime import date
from decimal import Decimal

import pytest

from finans.contracts.display import (
    class_label,
    day_label,
    exact,
    gap_text,
    money,
    month_label,
    percent,
    points,
    same_places,
)
from finans.domain.models import YearMonth

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


TODAY = date(2026, 11, 25)
MONTHS_WITH_SUFFIXES = [
    (1, "Ocak", "Ocak'ın", "Ocak'ta"),
    (2, "Şubat", "Şubat'ın", "Şubat'ta"),
    (3, "Mart", "Mart'ın", "Mart'ta"),
    (4, "Nisan", "Nisan'ın", "Nisan'da"),
    (5, "Mayıs", "Mayıs'ın", "Mayıs'ta"),
    (6, "Haziran", "Haziran'ın", "Haziran'da"),
    (7, "Temmuz", "Temmuz'un", "Temmuz'da"),
    (8, "Ağustos", "Ağustos'un", "Ağustos'ta"),
    (9, "Eylül", "Eylül'ün", "Eylül'de"),
    (10, "Ekim", "Ekim'in", "Ekim'de"),
    (11, "Kasım", "Kasım'ın", "Kasım'da"),
    (12, "Aralık", "Aralık'ın", "Aralık'ta"),
]


@pytest.mark.parametrize(("month", "plain", "genitive", "locative"), MONTHS_WITH_SUFFIXES)
def test_days_use_turkish_month_names_and_their_suffixes(
    month: int, plain: str, genitive: str, locative: str
) -> None:
    day = date(2026, month, 5)

    assert day_label(day, today=TODAY) == f"5 {plain}"
    assert day_label(day, today=TODAY, case="in") == f"5 {genitive}"
    assert day_label(day, today=TODAY, case="de") == f"5 {locative}"


@pytest.mark.parametrize(
    ("year", "genitive", "locative"),
    [
        (2026, "2026'nın", "2026'da"),
        (2025, "2025'in", "2025'te"),
        (2023, "2023'ün", "2023'te"),
        (2030, "2030'un", "2030'da"),
        (2040, "2040'ın", "2040'ta"),
        (2000, "2000'in", "2000'de"),
        (2100, "2100'ün", "2100'de"),
    ],
)
def test_a_shown_year_takes_the_suffix_by_how_it_is_read(
    year: int, genitive: str, locative: str
) -> None:
    day = date(year, 11, 25)

    assert day_label(day, today=TODAY, year=True, case="in") == f"25 Kasım {genitive}"
    assert day_label(day, today=TODAY, year=True, case="de") == f"25 Kasım {locative}"


def test_the_year_is_shown_only_when_it_differs_or_is_asked_for() -> None:
    assert day_label(date(2026, 11, 25), today=TODAY) == "25 Kasım"
    assert day_label(date(2025, 12, 31), today=TODAY) == "31 Aralık 2025"
    assert day_label(date(2026, 11, 25), today=TODAY, year=True) == "25 Kasım 2026"
    assert day_label(date(2027, 1, 2), today=date(2026, 12, 30)) == "2 Ocak 2027"


def test_a_month_is_named_with_its_year() -> None:
    assert month_label(YearMonth(2026, 10)) == "Ekim 2026"
    assert month_label(YearMonth(2026, 10), case="de") == "Ekim 2026'da"
    assert month_label("2026-10") == "Ekim 2026"


@pytest.mark.parametrize(
    ("values", "shown"),
    [
        ((D("10.500000"), D("11")), ("10,500000", "11,000000")),
        ((D("1.7443"), D("1.73"), D("1.744322")), ("1,744300", "1,730000", "1,744322")),
        ((D("22.5"), None), ("22,5", None)),
        ((D("3150"), D("3150.5")), ("3150,0", "3150,5")),
    ],
)
def test_compared_prices_share_the_larger_number_of_places(
    values: tuple[Decimal | None, ...], shown: tuple[str | None, ...]
) -> None:
    assert same_places(*values) == shown


@pytest.mark.parametrize(
    ("deviation", "text"),
    [(D("0.028"), "2,8 puan fazla"), (D("-0.0615"), "6,2 puan eksik"), (D("0"), "hedefte")],
)
def test_a_gap_to_the_target_is_said_without_a_gain_or_loss_sign(
    deviation: Decimal, text: str
) -> None:
    assert gap_text(deviation) == text
