"""Hata biçimi (K-138): `{"error": ileti, "fields": {alan: ileti}}`."""

import pytest
from fastapi import FastAPI
from pydantic import Field

from finans.api.errors import INVALID, UNREADABLE, ApiError, field_errors
from finans.api.models import Model
from tests.fakes.clock import FixedClock
from tests.support.api_client import ApiClient


class Trade(Model):
    amount: str = Field(max_length=20)
    note: str | None = None


@pytest.fixture
def writer(app: FastAPI, clock: FixedClock) -> ApiClient:
    @app.post("/api/deneme")
    def write(body: Trade) -> dict[str, str]:
        if body.amount == "değişti":
            raise ApiError(409, "Sonuç değişti; yeni önizlemeye bakın.", {"amount": "yeniden bak"})
        return {"amount": body.amount}

    return ApiClient(app, clock)


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({}, {"amount": "zorunlu"}),
        ({"amount": "1", "fazla": "x"}, {"fazla": "bilinmeyen alan"}),
        ({"amount": 5}, {"amount": "metin olmalı"}),
        ({"amount": "x" * 21}, {"amount": "çok uzun"}),
        ([1], {"gövde": "nesne olmalı"}),
    ],
)
def test_invalid_input_names_each_field(
    writer: ApiClient, body: object, fields: dict[str, str]
) -> None:
    response = writer.post("/api/deneme", json=body)
    assert (response.status_code, response.json()) == (422, {"error": INVALID, "fields": fields})


def test_a_body_that_is_not_json_is_unreadable(writer: ApiClient) -> None:
    response = writer.request(
        "POST", "/api/deneme", content=b"{bozuk", headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()) == (422, {"error": UNREADABLE, "fields": {}})


def test_an_empty_body_is_reported_as_missing(writer: ApiClient) -> None:
    response = writer.request(
        "POST", "/api/deneme", content=b"", headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()) == (
        422,
        {"error": INVALID, "fields": {"gövde": "zorunlu"}},
    )


def test_an_api_error_carries_its_status_message_and_fields(writer: ApiClient) -> None:
    response = writer.post("/api/deneme", json={"amount": "değişti"})
    assert (response.status_code, response.json()) == (
        409,
        {"error": "Sonuç değişti; yeni önizlemeye bakın.", "fields": {"amount": "yeniden bak"}},
    )


def test_field_names_lose_their_location_and_keep_the_first_message() -> None:
    errors: list[dict[str, object]] = [
        {"type": "int_parsing", "loc": ("query", "sayfa")},
        {"type": "greater_than", "loc": ("query", "sayfa")},
        {"type": "bilinmeyen_tur", "loc": ("body", "satirlar", 0, "fon")},
        {"type": "missing", "loc": ()},
    ]
    assert field_errors(errors) == (
        False,
        {"sayfa": "tamsayı olmalı", "satirlar.0.fon": "geçersiz", "gövde": "zorunlu"},
    )
