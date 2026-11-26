"""Eşlik fikstürü repodadır; Vitest istemcinin aynı metni ürettiğini denetler (K-139)."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from finans.api.parity import CASES, main, render

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "format" / "parity.json"


def test_the_fixture_in_the_repository_is_current() -> None:
    # Dosyayı Biome biçimler; karşılaştırılan içeriktir.
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored == json.loads(render()), "Fikstürü `make bicim` ile yeniden üret."


def test_main_prints_the_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    assert capsys.readouterr().out == render()


def leaves(node: object, key: str | None = None) -> Iterator[tuple[str | None, object]]:
    if isinstance(node, dict):
        for name, value in node.items():
            yield from leaves(value, name)
    elif isinstance(node, list):
        for item in node:
            yield from leaves(item, key)
    else:
        yield key, node


def test_decimals_travel_as_text_never_as_json_numbers() -> None:
    found = list(leaves(json.loads(render())))

    assert all(isinstance(value, str | int | None) for _, value in found)
    numbers = {
        key for key, value in found if isinstance(value, int) and not isinstance(value, bool)
    }
    assert numbers == {"places"}


def test_every_grammatical_case_appears_for_days_and_months() -> None:
    data = json.loads(render())

    assert {row["case"] for row in data["day"]} == set(CASES)
    assert {row["case"] for row in data["month"]} == set(CASES)


@pytest.mark.parametrize(
    ("key", "row"),
    [
        ("money", {"value": "0.125", "text": "0,12 TL"}),
        ("money", {"value": "0.135", "text": "0,14 TL"}),
        ("money", {"value": "-0.004", "text": "0,00 TL"}),
        ("gap", {"value": "-0.0005", "text": "hedefte"}),
        ("gap", {"value": "0.0015", "text": "0,2 puan fazla"}),
        ("exact", {"value": "12.838270", "text": "12,83827"}),
    ],
)
def test_the_fixture_holds_the_rounding_edges(key: str, row: dict[str, str]) -> None:
    assert row in json.loads(render())[key]
