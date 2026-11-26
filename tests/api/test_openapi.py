"""OpenAPI şeması repodadır ve TypeScript tiplerinin tek kaynağıdır (K-138)."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from finans.api.app import openapi_document
from finans.api.openapi import main, render

SCHEMA = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json"


def test_the_schema_in_the_repository_is_current() -> None:
    assert SCHEMA.read_text(encoding="utf-8") == render(), "Şemayı `make openapi` ile yeniden üret."


def schema_types(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        kind = node.get("type")
        if isinstance(kind, str):
            yield kind
        elif isinstance(kind, list):
            yield from (item for item in kind if isinstance(item, str))
        for value in node.values():
            yield from schema_types(value)
    elif isinstance(node, list):
        for item in node:
            yield from schema_types(item)


@pytest.mark.parametrize(
    "node",
    [{"type": "number"}, {"a": [{"type": ["number", "null"]}]}, {"anyOf": [{"type": "number"}]}],
)
def test_the_type_walk_finds_numbers_anywhere(node: object) -> None:
    assert "number" in set(schema_types(node))


def test_no_schema_uses_the_number_type() -> None:
    assert "number" not in set(schema_types(openapi_document()))


def test_every_path_is_under_api() -> None:
    assert all(path.startswith("/api/") for path in openapi_document()["paths"])


def test_errors_use_the_api_error_body_not_fastapis() -> None:
    document = json.dumps(openapi_document())
    assert "HTTPValidationError" not in document
    assert "ErrorBody" in document


def test_main_prints_the_schema(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    assert capsys.readouterr().out == render()
