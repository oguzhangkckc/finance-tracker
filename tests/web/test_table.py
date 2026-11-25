"""Tablo sorgusu: sıralama, filtre ve sayfalama adres parametreleriyle, Python'da (K-129)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qsl

import pytest

from finans.web.table import Choice, Column, TableSpec, table

D = Decimal


@dataclass(frozen=True)
class Row:
    no: int
    day: date
    code: str
    amount: Decimal
    note: str = ""


SPEC = TableSpec[Row](
    columns=(
        Column("no", "No", lambda r: r.no),
        Column("tarih", "Tarih", lambda r: r.day, ("eskiden yeniye", "yeniden eskiye")),
        Column("fon", "Fon", lambda r: r.code, ("A'dan Z'ye", "Z'den A'ya")),
        Column("tutar", "Tutar", lambda r: r.amount, ("küçükten büyüğe", "büyükten küçüğe")),
    ),
    default_sort="tarih",
    default_descending=True,
    tiebreak=lambda r: r.no,
    choices=(
        Choice(
            "fon",
            "Fon",
            lambda rows: [(code, code) for code in sorted({r.code for r in rows})],
            lambda r, value: r.code == value,
        ),
    ),
    day=lambda r: r.day,
    search=lambda r: f"{r.code} {r.note}",
)
ROWS = [
    Row(1, date(2026, 11, 2), "XHT", D("9"), "ilk alım"),
    Row(2, date(2026, 11, 2), "XPP", D("10"), "D-7"),
    Row(3, date(2026, 11, 20), "XHT", D("100.5")),
    Row(4, date(2026, 11, 25), "XAL", D("9.99")),
]


def _query(url: str) -> dict[str, str]:
    return dict(parse_qsl(url.removeprefix("?")))


def _numbers(params: dict[str, str], rows: list[Row] = ROWS) -> list[int]:
    return [r.no for r in table(rows, params, SPEC).rows]


def test_the_default_is_newest_first_with_the_number_breaking_ties() -> None:
    assert _numbers({}) == [4, 3, 2, 1]
    assert _numbers({"yon": "artan"}) == [1, 2, 3, 4]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"sirala": "tutar", "yon": "artan"}, [1, 4, 2, 3]),
        ({"sirala": "tutar", "yon": "azalan"}, [3, 2, 4, 1]),
        ({"sirala": "fon", "yon": "artan"}, [4, 1, 3, 2]),
        ({"sirala": "no", "yon": "azalan"}, [4, 3, 2, 1]),
    ],
)
def test_each_column_sorts_both_ways_and_decimals_sort_as_numbers(
    params: dict[str, str], expected: list[int]
) -> None:
    assert _numbers(params) == expected


def test_filters_combine_and_the_date_range_is_inclusive() -> None:
    assert _numbers({"fon": "XHT"}) == [3, 1]
    assert _numbers({"bas": "2026-11-02", "bit": "2026-11-20"}) == [3, 2, 1]
    assert _numbers({"fon": "XHT", "bas": "2026-11-03"}) == [3]
    assert _numbers({"ara": "d-7"}) == [2]
    assert _numbers({"ara": "İLK"}) == [1]


@pytest.mark.parametrize(
    ("params", "note"),
    [
        ({"sirala": "renk"}, "sirala=renk"),
        ({"yon": "yukari"}, "yon=yukari"),
        ({"fon": "XYZ"}, "fon=XYZ"),
        ({"bas": "25.11.2026"}, "bas=25.11.2026"),
        ({"sayfa": "0"}, "sayfa=0"),
        ({"sayfa": "iki"}, "sayfa=iki"),
        ({"renk": "mavi"}, "renk=mavi"),
        ({"bas": "2026-11-25", "bit": "2026-11-02"}, "bas=2026-11-25, bit=2026-11-02"),
    ],
)
def test_a_misunderstood_parameter_is_ignored_and_named(params: dict[str, str], note: str) -> None:
    view = table(ROWS, params, SPEC)

    assert [r.no for r in view.rows] == [4, 3, 2, 1]
    assert view.misunderstood == note


def test_page_level_parameters_are_not_misunderstood() -> None:
    params = {"islem": "alis", "no": "5", "istek": "alindi"}

    view = table(ROWS, params, SPEC, passthrough=("islem", "no", "istek"))

    assert view.misunderstood == ""


@pytest.mark.parametrize(("count", "pages", "last"), [(0, 1, 0), (25, 1, 25), (26, 2, 1)])
def test_pages_hold_twenty_five_rows(count: int, pages: int, last: int) -> None:
    rows = [Row(n, date(2026, 11, 2), "XHT", D(n)) for n in range(1, count + 1)]

    view = table(rows, {"sayfa": str(pages)}, SPEC)

    assert (view.pages, view.page, len(view.rows), view.total) == (pages, pages, last, count)


def test_a_page_past_the_end_shows_the_last_page() -> None:
    rows = [Row(n, date(2026, 11, 2), "XHT", D(n)) for n in range(1, 27)]

    view = table(rows, {"sayfa": "9"}, SPEC)

    assert (view.page, [r.no for r in view.rows]) == (2, [1])


def test_links_keep_the_filters_and_reset_the_page() -> None:
    view = table(ROWS, {"fon": "XHT", "sirala": "tutar", "yon": "artan", "sayfa": "1"}, SPEC)

    assert _query(view.url(sayfa="2")) == {
        "fon": "XHT",
        "sirala": "tutar",
        "yon": "artan",
        "sayfa": "2",
    }
    assert _query(view.sort_url("tutar")) == {"fon": "XHT", "sirala": "tutar", "yon": "azalan"}
    assert _query(view.sort_url("fon")) == {"fon": "XHT", "sirala": "fon", "yon": "artan"}
    assert view.aria_sort("tutar") == "ascending"
    assert view.aria_sort("fon") == "none"


def test_active_filters_can_each_be_removed() -> None:
    view = table(ROWS, {"fon": "XHT", "ara": "ilk", "bas": "2026-11-01"}, SPEC)

    removals = {(chip.name, chip.value): _query(chip.remove) for chip in view.active}
    assert removals == {
        ("Fon", "XHT"): {"ara": "ilk", "bas": "2026-11-01"},
        ("Arama", "ilk"): {"fon": "XHT", "bas": "2026-11-01"},
        ("Başlangıç", "2026-11-01"): {"fon": "XHT", "ara": "ilk"},
    }
    assert [chip.day for chip in view.active] == [False, False, True]


def test_the_single_sort_select_sets_column_and_direction_in_canonical_links() -> None:
    view = table(ROWS, {"siralama": "tutar.azalan", "fon": "XHT"}, SPEC)

    assert [r.no for r in view.rows] == [3, 1]
    assert _query(view.url()) == {"fon": "XHT", "sirala": "tutar", "yon": "azalan"}
    assert view.sort_choices[2:4] == [
        ("tarih.artan", "Tarih: eskiden yeniye", False),
        ("tarih.azalan", "Tarih: yeniden eskiye", False),
    ]
    assert ("tutar.azalan", "Tutar: büyükten küçüğe", True) in view.sort_choices


def test_a_bad_sort_select_is_misunderstood() -> None:
    assert table(ROWS, {"siralama": "renk.artan"}, SPEC).misunderstood == "siralama=renk.artan"


def test_empty_form_fields_are_not_filters_and_not_misunderstood() -> None:
    view = table(ROWS, {"fon": "", "ara": "", "bas": "", "bit": "", "siralama": ""}, SPEC)

    assert ([r.no for r in view.rows], view.misunderstood, view.active) == ([4, 3, 2, 1], "", [])
