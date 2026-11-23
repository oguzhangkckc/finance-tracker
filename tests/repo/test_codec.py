from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finans.adapters.sqlite.codec import (
    decode_date,
    decode_decimal,
    encode_date,
    encode_decimal,
    encode_timestamp,
)

D = Decimal


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (D("100"), "100"),
        (D("1E+2"), "100"),
        (D("1.500"), "1.5"),
        (D("0.000001"), "0.000001"),
        (D("-0"), "0"),
        (D("-0.000"), "0"),
        (D("-12.340"), "-12.34"),
        (D("1.123456789012345678901234567890"), "1.12345678901234567890123456789"),
    ],
)
def test_decimal_is_encoded_canonically(value: Decimal, text: str) -> None:
    assert encode_decimal(value) == text


@pytest.mark.parametrize("value", [D("NaN"), D("Infinity"), D("-Infinity")])
def test_non_finite_decimal_is_rejected(value: Decimal) -> None:
    with pytest.raises(ValueError, match="sonlu"):
        encode_decimal(value)


@pytest.mark.parametrize("text", ["1E+2", "1.50", "-0", "01", ".5", "1,5", " 1", "abc", "NaN"])
def test_non_canonical_text_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="Decimal değil"):
        decode_decimal(text)


@given(st.decimals(allow_nan=False, allow_infinity=False, places=8, max_value=D("1e12")))
def test_decimal_round_trip(value: Decimal) -> None:
    assert decode_decimal(encode_decimal(value)) == value


def test_date_round_trip_and_strict_format() -> None:
    assert encode_date(date(2026, 2, 3)) == "2026-02-03"
    assert decode_date("2026-02-03") == date(2026, 2, 3)
    for text in ["20260203", "2026-2-3", "2026-02-30"]:
        with pytest.raises(ValueError, match="YYYY-AA-GG"):
            decode_date(text)


def test_timestamp_is_stored_as_utc_iso_seconds() -> None:
    istanbul_evening = datetime(
        2026, 11, 23, 23, 30, 15, 123456, tzinfo=timezone(timedelta(hours=3))
    )
    assert encode_timestamp(istanbul_evening) == "2026-11-23T20:30:15+00:00"


def test_utc_timestamp_round_trips() -> None:
    value = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    assert datetime.fromisoformat(encode_timestamp(value)) == value


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="saat dilimi"):
        encode_timestamp(datetime(2026, 11, 23, 12, 0))  # noqa: DTZ001
