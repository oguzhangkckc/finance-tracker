"""Yazma güvenliği (K-137): yalnız JSON, bu köken, aynı site; CORS başlığı hiçbir yanıtta yok."""

import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import Field

from finans.api.middleware import MAX_BODY_BYTES
from finans.api.models import Model
from tests.fakes.clock import FixedClock
from tests.support.api_client import ACCESS_HEADER, ApiClient

DENIED = {"error": "Erişim reddedildi.", "fields": {}}
JSON_ONLY = {"error": "Yalnız application/json kabul edilir.", "fields": {}}
BODY = b'{"text": "a"}'


class Note(Model):
    text: str = Field(max_length=20)


@pytest.fixture
def writes(app: FastAPI) -> list[str]:
    saved: list[str] = []

    @app.post("/api/deneme")
    def write(body: Note) -> dict[str, str]:
        saved.append(body.text)
        return {"saved": body.text}

    return saved


@pytest.fixture
def writer(app: FastAPI, clock: FixedClock, writes: list[str]) -> ApiClient:
    return ApiClient(app, clock)


def cors_headers(response: httpx.Response) -> list[str]:
    return [name for name in response.headers if name.lower().startswith("access-control-")]


def test_a_same_origin_json_write_goes_through(writer: ApiClient, writes: list[str]) -> None:
    response = writer.post("/api/deneme", json={"text": "a"})
    assert (response.status_code, response.json(), writes) == (200, {"saved": "a"}, ["a"])


@pytest.mark.parametrize("media", ["application/json; charset=utf-8", "Application/JSON"])
def test_json_with_parameters_or_other_case_is_json(writer: ApiClient, media: str) -> None:
    response = writer.request("POST", "/api/deneme", content=BODY, headers={"Content-Type": media})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "media",
    [
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "text/plain",
        "application/json-patch+json",
        None,
    ],
)
def test_anything_but_json_is_refused_with_415(
    writer: ApiClient, writes: list[str], media: str | None
) -> None:
    headers = {} if media is None else {"Content-Type": media}
    response = writer.request("POST", "/api/deneme", content=BODY, headers=headers)
    assert (response.status_code, response.json(), writes) == (415, JSON_ONLY, [])


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "https://baska.example.com",
        "http://finans.example.com",
        "https://finans.example.com.baska.example.com",
        "https://finans.example.com:8443",
    ],
)
def test_a_write_from_another_origin_is_denied(
    writer: ApiClient, writes: list[str], caplog: pytest.LogCaptureFixture, origin: str | None
) -> None:
    with caplog.at_level(logging.WARNING, logger="finans.api"):
        if origin is None:
            response = writer.post("/api/deneme", json={"text": "a"}, drop=("Origin",))
        else:
            response = writer.post("/api/deneme", json={"text": "a"}, headers={"Origin": origin})

    assert (response.status_code, response.json(), writes) == (403, DENIED, [])
    assert [r.getMessage() for r in caplog.records] == [
        "Yazma reddedildi: POST /api/deneme: köken farklı"
    ]


@pytest.mark.parametrize("site", [None, "cross-site", "same-site", "none"])
def test_a_write_that_is_not_same_site_is_denied(
    writer: ApiClient, writes: list[str], caplog: pytest.LogCaptureFixture, site: str | None
) -> None:
    with caplog.at_level(logging.WARNING, logger="finans.api"):
        if site is None:
            response = writer.post("/api/deneme", json={"text": "a"}, drop=("Sec-Fetch-Site",))
        else:
            response = writer.post(
                "/api/deneme", json={"text": "a"}, headers={"Sec-Fetch-Site": site}
            )

    assert (response.status_code, response.json(), writes) == (403, DENIED, [])
    assert [r.getMessage() for r in caplog.records] == [
        "Yazma reddedildi: POST /api/deneme: Sec-Fetch-Site same-origin değil"
    ]


def test_identity_is_checked_before_the_write_rules(
    app: FastAPI, clock: FixedClock, writes: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="finans.api"):
        response = ApiClient(app, clock, signed=False).request(
            "POST",
            "/api/deneme",
            content=b"text=a",
            headers={"Origin": "https://baska.example.com"},
        )

    assert (response.status_code, writes) == (403, [])
    assert [r.getMessage() for r in caplog.records] == [
        "Erişim reddedildi: POST /api/deneme: başlık yok"
    ]


def test_reading_is_not_subject_to_the_write_rules(writer: ApiClient) -> None:
    response = writer.get(
        "/api/oturum",
        headers={"Origin": "https://baska.example.com", "Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 200
    assert cors_headers(response) == []


def test_a_cors_preflight_gets_no_permission(writer: ApiClient) -> None:
    response = writer.request(
        "OPTIONS",
        "/api/deneme",
        headers={
            "Origin": "https://baska.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 405
    assert cors_headers(response) == []


def test_no_response_carries_a_cors_header(
    app: FastAPI, clock: FixedClock, writer: ApiClient
) -> None:
    foreign = {"Origin": "https://baska.example.com"}
    responses = [
        writer.post("/api/deneme", json={"text": "a"}),
        writer.post("/api/deneme", json={"text": "a"}, headers=foreign),
        writer.request("POST", "/api/deneme", content=BODY, headers={"Content-Type": "text/plain"}),
        writer.get("/api/oturum", headers=foreign),
        ApiClient(app, clock, signed=False).get("/api/oturum", headers=foreign),
        writer.get("/api/saglik", headers=foreign),
    ]
    assert [cors_headers(response) for response in responses] == [[]] * len(responses)


def test_a_body_over_the_limit_is_refused(writer: ApiClient, writes: list[str]) -> None:
    response = writer.post("/api/deneme", json={"text": "a" * MAX_BODY_BYTES})
    assert (response.status_code, response.json(), writes) == (
        413,
        {"error": "İstek çok büyük.", "fields": {}},
        [],
    )


def test_a_write_without_a_length_is_refused(writer: ApiClient, writes: list[str]) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield BODY

    response = writer.request(
        "POST", "/api/deneme", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, writes) == (411, [])


def test_the_access_header_is_what_identifies(writer: ApiClient) -> None:
    response = writer.post("/api/deneme", json={"text": "a"}, drop=(ACCESS_HEADER,))
    assert response.status_code == 403
