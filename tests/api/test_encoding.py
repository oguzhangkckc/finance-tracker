"""Decimal yanıtta K-52'deki kanonik metindir; rapor kontratı değişmeden (K-138)."""

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel

from finans.api.encoding import CanonicalJSONResponse, plain
from finans.api.models import CANONICAL_DECIMAL, DecimalStr
from finans.contracts.report import ValueSplit


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("100.00"), "100"),
        (Decimal("0E-10"), "0"),
        (Decimal("1.2E+3"), "1200"),
        (Decimal("-0"), "0"),
        (Decimal("-12.50"), "-12.5"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("12.838270"), "12.83827"),
    ],
)
def test_decimals_are_written_canonically(value: Decimal, text: str) -> None:
    assert plain(value) == text
    assert re.fullmatch(CANONICAL_DECIMAL, text)


def test_a_report_contract_model_is_written_canonically_without_changing_it() -> None:
    split = ValueSplit(
        in_allocation=Decimal("1E+3"), out_of_allocation=Decimal("0E-10"), total=Decimal("1000.00")
    )
    assert CanonicalJSONResponse(split).body == (
        b'{"in_allocation":"1000","out_of_allocation":"0","total":"1000"}'
    )
    assert json.loads(split.model_dump_json())["in_allocation"] == "1E+3"


def test_dates_lists_and_mappings_are_written_as_json() -> None:
    value = {
        "gun": date(2026, 11, 26),
        "an": datetime(2026, 11, 26, 9, 0, tzinfo=UTC),
        "liste": (1, [Decimal("2.0")], None, True, "metin"),
    }
    assert plain(value) == {
        "gun": "2026-11-26",
        "an": "2026-11-26T09:00:00+00:00",
        "liste": [1, ["2"], None, True, "metin"],
    }


@pytest.mark.parametrize("value", [object(), b"bayt", {1, 2}])
def test_an_unknown_type_is_an_error_not_a_guess(value: object) -> None:
    with pytest.raises(TypeError, match="JSON'a yazılamayan tip"):
        plain(value)


class Priced(BaseModel):
    price: DecimalStr


def test_decimal_str_is_canonical_text_in_json_and_in_the_schema() -> None:
    assert Priced(price=Decimal("12.50")).model_dump(mode="json") == {"price": "12.5"}
    schema = Priced.model_json_schema(mode="serialization")["properties"]["price"]
    assert {key: schema[key] for key in ("type", "pattern")} == {
        "type": "string",
        "pattern": CANONICAL_DECIMAL,
    }


@pytest.mark.parametrize("text", ["1E+3", "100.0", "01", "-0", ".5", "1.", "0.0", "+1", "1,5"])
def test_the_canonical_pattern_rejects_other_spellings(text: str) -> None:
    assert re.fullmatch(CANONICAL_DECIMAL, text) is None
