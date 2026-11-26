"""API iskeleti (K-136…K-138): kimlik yönlendirmeden önce, güvenlik başlıkları her
yanıtta, hatalar JSON."""

import asyncio
import logging
from collections.abc import MutableMapping
from pathlib import Path

import pytest
from fastapi import FastAPI

from finans.api.app import create_app
from finans.api.errors import UNEXPECTED
from finans.api.middleware import SECURITY_HEADERS
from finans.settings import Settings
from tests.fakes.access import FakeAccessKeys
from tests.fakes.clock import FixedClock
from tests.support.access import API_SETTINGS, EMAIL, access_token, public_jwk
from tests.support.api_client import ACCESS_HEADER, ApiClient

DENIED = {"error": "Erişim reddedildi.", "fields": {}}


def security_headers(response_headers: object) -> dict[str, str | None]:
    assert hasattr(response_headers, "get")
    return {name: response_headers.get(name) for name in SECURITY_HEADERS}


def test_health_needs_no_identity_and_says_nothing_else(app: FastAPI, clock: FixedClock) -> None:
    response = ApiClient(app, clock, signed=False).get("/api/saglik")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_every_response_carries_the_security_headers(app: FastAPI, clock: FixedClock) -> None:
    anonymous = ApiClient(app, clock, signed=False)
    viewer = ApiClient(app, clock)
    for response in (
        anonymous.get("/api/saglik"),
        anonymous.get("/api/oturum"),
        viewer.get("/api/oturum"),
        viewer.get("/api/yok"),
    ):
        assert security_headers(response.headers) == SECURITY_HEADERS


@pytest.mark.parametrize(
    "path", ["/api/oturum", "/api/yok", "/api/gercek/ozet", "/", "/api/saglik/"]
)
def test_without_identity_every_other_path_is_denied_without_detail(
    app: FastAPI, clock: FixedClock, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    with caplog.at_level(logging.WARNING, logger="finans.api"):
        response = ApiClient(app, clock, signed=False).get(path)

    assert (response.status_code, response.json()) == (403, DENIED)
    assert [r.getMessage() for r in caplog.records] == [
        f"Erişim reddedildi: GET {path}: başlık yok"
    ]


def test_another_account_is_denied_and_the_log_names_neither_it_nor_the_token(
    app: FastAPI, clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    token = access_token(clock.now(), email="baska@example.com")
    with caplog.at_level(logging.WARNING, logger="finans.api"):
        response = ApiClient(app, clock, signed=False).get(
            "/api/oturum", headers={ACCESS_HEADER: token}
        )

    assert (response.status_code, response.json()) == (403, DENIED)
    assert [r.getMessage() for r in caplog.records] == [
        "Erişim reddedildi: GET /api/oturum: e-posta izinli değil"
    ]
    assert token not in caplog.text


def test_the_session_names_the_viewer_and_both_profiles(client: ApiClient) -> None:
    assert client.get("/api/oturum").json() == {
        "email": EMAIL,
        "profiles": [{"slug": "gercek", "label": "Gerçek"}, {"slug": "sanal", "label": "Sanal"}],
        "default_profile": "gercek",
    }


def test_the_default_profile_follows_the_service_setting(
    tmp_path: Path, clock: FixedClock, keys: FakeAccessKeys
) -> None:
    settings = Settings(db_path=tmp_path / "finans.db", profile="sanal")
    app = create_app(settings, API_SETTINGS, keys=keys, clock=clock)
    assert ApiClient(app, clock).get("/api/oturum").json()["default_profile"] == "sanal"


def test_an_unknown_path_is_a_json_404(client: ApiClient) -> None:
    response = client.get("/api/yok")
    assert (response.status_code, response.json()) == (404, {"error": "Bulunamadı.", "fields": {}})


def test_a_wrong_method_is_a_json_405(client: ApiClient) -> None:
    response = client.post("/api/oturum", json={})
    assert (response.status_code, response.json()) == (
        405,
        {"error": "Bu yöntem desteklenmiyor.", "fields": {}},
    )
    assert response.headers["allow"] == "GET"


def test_an_unexpected_error_is_a_500_without_detail(app: FastAPI, clock: FixedClock) -> None:
    @app.get("/api/patla")
    def explode() -> None:
        raise RuntimeError("gizli ayrıntı")

    response = ApiClient(app, clock, raise_errors=False).get("/api/patla")

    assert (response.status_code, response.json()) == (500, {"error": UNEXPECTED, "fields": {}})
    assert "gizli" not in response.text
    assert security_headers(response.headers) == SECURITY_HEADERS


def test_the_docs_and_the_schema_are_not_served(client: ApiClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404


def test_building_the_app_does_not_fetch_keys(app: FastAPI, keys: FakeAccessKeys) -> None:
    assert keys.calls == 0


def test_keys_are_fetched_at_startup_and_reused(
    app: FastAPI, clock: FixedClock, keys: FakeAccessKeys
) -> None:
    response = ApiClient(app, clock, startup=True).get("/api/oturum")
    assert (response.status_code, keys.calls) == (200, 1)


def test_a_failed_fetch_at_startup_keeps_the_service_up_but_denies(
    settings: Settings, clock: FixedClock
) -> None:
    keys = FakeAccessKeys([public_jwk()], down=True)
    app = create_app(settings, API_SETTINGS, keys=keys, clock=clock)

    response = ApiClient(app, clock, startup=True).get("/api/oturum")
    assert (response.status_code, keys.calls) == (403, 1)
    assert ApiClient(app, clock, signed=False).get("/api/saglik").status_code == 200


def test_the_asgi_lifespan_fetches_keys_as_the_server_would(
    app: FastAPI, keys: FakeAccessKeys
) -> None:
    async def run() -> list[str]:
        incoming = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
        sent: list[str] = []

        async def receive() -> dict[str, str]:
            return incoming.pop(0)

        async def send(message: MutableMapping[str, object]) -> None:
            sent.append(str(message["type"]))

        await app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)
        return sent

    assert asyncio.run(run()) == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert keys.calls == 1
