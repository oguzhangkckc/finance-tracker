from datetime import date
from decimal import Decimal

import pytest

from finans.application.inputs import InputError, parse_amount, parse_day, parse_period
from finans.domain.models import YearMonth


def test_amount_keeps_the_entered_places() -> None:
    value = parse_amount("price", "1.230000")

    assert value == Decimal("1.23")
    assert value.as_tuple().exponent == -6


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("12,5", "units: ondalık ayırıcı nokta olmalı; 12,5 yerine 12.5 yaz."),
        ("abc", "units: sayı olmalı, 'abc' verildi."),
        ("1.234,5", "units: sayı olmalı, '1.234,5' verildi."),
        ("", "units: sayı olmalı, '' verildi."),
    ],
)
def test_malformed_amounts_say_what_to_write(text: str, message: str) -> None:
    with pytest.raises(InputError) as caught:
        parse_amount("units", text)

    assert str(caught.value) == message


def test_day_must_be_written_exactly_as_iso() -> None:
    assert parse_day("2026-06-15") == date(2026, 6, 15)
    for text in ("2026-6-15", "20260615", "2026-02-30", "15.06.2026"):
        with pytest.raises(InputError, match=r"Tarih YYYY-AA-GG biçiminde olmalı"):
            parse_day(text)


def test_period_must_be_a_real_month() -> None:
    assert parse_period("2026-06") == YearMonth(2026, 6)
    with pytest.raises(InputError) as caught:
        parse_period("2026-13")

    assert str(caught.value) == "Dönem YYYY-AA biçiminde geçerli bir ay olmalı, '2026-13' verildi."
