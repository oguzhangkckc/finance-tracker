"""Biçimlendirme eşlik fikstürü; `make bicim` repodaki `frontend/src/format/parity.json`'ı üretir.

Arayüz Decimal'i API'nin gönderdiği metinden kendisi biçimler (K-138). Fikstürün her satırı
`contracts/display`'in ürettiği metindir; Vitest istemcinin aynısını ürettiğini denetler (K-139).
"""

import json
import sys
from datetime import date
from decimal import Decimal
from typing import Final

from finans.contracts.display import (
    Case,
    day_label,
    exact,
    gap_text,
    money,
    month_label,
    percent,
    points,
    same_places,
)
from finans.contracts.report import SANAL_NOTICE
from finans.sunum.profiles import PROFILE_LABELS, SLUGS

TODAY: Final = date(2026, 11, 26)
CASES: Final[tuple[Case, ...]] = ("", "in", "de", "den")

# Banker yuvarlamasının iki yönü, sıfıra yuvarlanan eksi değer, binlik ayırıcı.
AMOUNTS: Final = (
    "0",
    "0.5",
    "0.005",
    "0.015",
    "0.125",
    "0.135",
    "-0.125",
    "-0.004",
    "999.995",
    "-999.995",
    "1234.565",
    "1234.575",
    "1234567.891",
    "-1000000",
    "0.000001",
)
RATES: Final = (
    "0",
    "0.047058",
    "-0.012",
    "0.444",
    "0.00005",
    "0.000049",
    "-0.00005",
    "0.000125",
    "1",
    "12.3456",
    "-0.5",
)
PLACES: Final = (0, 1, 2, 4)
DEVIATIONS: Final = (
    "0",
    "0.028",
    "-0.0615",
    "0.04396",
    "-0.04396",
    "0.0005",
    "0.00049",
    "-0.0005",
    "-0.00051",
    "0.0015",
    "0.25",
    "-1",
)
EXACT: Final = ("0", "12.83827", "12.838270", "4050", "0.000001", "-0.5", "1234567.000001")
GROUPS: Final[tuple[tuple[str | None, ...], ...]] = (
    ("10.500000", "11"),
    ("1.7443", "1.73", "1.744322"),
    ("22.5", None),
    ("3150", "3150.5"),
    ("-1.5", "2.25"),
    ("0", "0.0"),
    (None, None),
)
# Okunuştaki son kelime: birler, onlar, yüz, bin; ünlü uyumu ve sert ünsüz için hepsi.
YEARS: Final = (
    2000,
    2001,
    2010,
    2020,
    2022,
    2023,
    2024,
    2025,
    2027,
    2028,
    2029,
    2030,
    2040,
    2050,
    2060,
    2070,
    2080,
    2090,
    2100,
)
DAYS: Final[tuple[tuple[date, bool | None], ...]] = (
    *((date(TODAY.year, month, 9), None) for month in range(1, 13)),
    (date(TODAY.year, 2, 25), True),
    (date(TODAY.year, 11, 25), True),
    *((date(year, 3, 9), None) for year in YEARS),
    (date(2025, 12, 31), False),
)
PERIODS: Final = (
    *(f"{TODAY.year}-{month:02d}" for month in range(1, 13)),
    *(f"{year}-10" for year in YEARS),
)


def _optional(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def fixture() -> dict[str, object]:
    return {
        "money": [{"value": value, "text": money(Decimal(value))} for value in AMOUNTS],
        "percent": [
            {
                "value": value,
                "places": places,
                "signed": signed,
                "text": percent(Decimal(value), places=places, signed=signed),
            }
            for value in RATES
            for places in PLACES
            for signed in (False, True)
        ],
        "points": [{"value": value, "text": points(Decimal(value))} for value in DEVIATIONS],
        "gap": [{"value": value, "text": gap_text(Decimal(value))} for value in DEVIATIONS],
        "exact": [{"value": value, "text": exact(Decimal(value))} for value in EXACT],
        "same_places": [
            {"values": list(group), "texts": list(same_places(*map(_optional, group)))}
            for group in GROUPS
        ],
        "day": [
            {
                "day": day.isoformat(),
                "today": TODAY.isoformat(),
                "case": case,
                "year": year,
                "text": day_label(day, today=TODAY, case=case, year=year),
            }
            for day, year in DAYS
            for case in CASES
        ],
        "month": [
            {"period": period, "case": case, "text": month_label(period, case=case)}
            for period in PERIODS
            for case in CASES
        ],
        "labels": {
            "profiles": {SLUGS[profile]: label for profile, label in PROFILE_LABELS.items()},
            "sanal_notice": SANAL_NOTICE,
        },
    }


def render() -> str:
    return json.dumps(fixture(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    sys.stdout.write(render())


if __name__ == "__main__":
    main()
