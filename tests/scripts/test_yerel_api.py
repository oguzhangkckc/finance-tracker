"""Yerel başlatıcı (K-139): API kendi ürettiği anahtara güvenir; doğrulama kapatılmaz."""

import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import jwt
import pytest
import uvicorn

from finans.api.app import create_app
from finans.settings import Settings
from scripts import yerel_api
from tests.fakes.clock import FixedClock
from tests.support.access import access_token
from tests.support.api_client import ApiClient

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
HEADER = "Cf-Access-Jwt-Assertion"


@pytest.fixture
def launch() -> yerel_api.Launch:
    return yerel_api.prepare(8765, NOW)


def client(launch: yerel_api.Launch, tmp_path: Path) -> ApiClient:
    clock = FixedClock(NOW)
    settings = Settings(db_path=tmp_path / "finans.db")
    app = create_app(settings, launch.settings, keys=launch.keys, clock=clock)
    return ApiClient(app, clock, signed=False)


def test_the_api_accepts_the_local_token(launch: yerel_api.Launch, tmp_path: Path) -> None:
    response = client(launch, tmp_path).get("/api/oturum", headers={HEADER: launch.token})

    assert response.status_code == 200
    assert response.json()["email"] == yerel_api.EMAIL


def test_verification_is_not_switched_off(launch: yerel_api.Launch, tmp_path: Path) -> None:
    api = client(launch, tmp_path)
    earlier_run = yerel_api.prepare(8765, NOW)

    assert api.get("/api/oturum").status_code == 403
    assert api.get("/api/oturum", headers={HEADER: access_token(NOW)}).status_code == 403
    assert api.get("/api/oturum", headers={HEADER: earlier_run.token}).status_code == 403


def test_writes_pass_csrf_only_with_the_rewritten_origin(
    launch: yerel_api.Launch, tmp_path: Path
) -> None:
    api = client(launch, tmp_path)
    headers = {HEADER: launch.token, "Sec-Fetch-Site": "same-origin"}

    rewritten = api.request(
        "POST",
        "/api/gercek/fiyat-guncelle",
        json={},
        headers={**headers, "Origin": yerel_api.ORIGIN},
    )
    browser = api.request(
        "POST",
        "/api/gercek/fiyat-guncelle",
        json={},
        headers={**headers, "Origin": "http://localhost:5173"},
    )

    assert rewritten.status_code != 403
    assert browser.status_code == 403


def test_the_token_lasts_a_day_and_names_the_local_audience(launch: yerel_api.Launch) -> None:
    claims = jwt.decode(launch.token, options={"verify_signature": False})

    assert claims["exp"] - claims["iat"] == 24 * 3600
    assert (claims["aud"], claims["email"]) == (yerel_api.AUDIENCE, yerel_api.EMAIL)
    assert claims["iss"] == f"https://{yerel_api.TEAM}"
    assert jwt.get_unverified_header(launch.token)["kid"] == yerel_api.KID


def test_each_run_listens_on_loopback_with_its_own_confirmation_key(
    launch: yerel_api.Launch,
) -> None:
    other = yerel_api.prepare(8765, NOW)

    assert launch.settings.host == "127.0.0.1"
    assert launch.settings.dist == Path(yerel_api.ROOT) / "frontend" / "dist"
    assert len(launch.settings.confirm_key.get_secret_value()) >= 32
    key = launch.settings.confirm_key.get_secret_value()
    assert key != other.settings.confirm_key.get_secret_value()


def test_the_env_file_is_readable_only_by_its_owner(
    launch: yerel_api.Launch, tmp_path: Path
) -> None:
    path = tmp_path / ".env.local"
    path.write_text("eski\n", encoding="utf-8")
    path.chmod(0o644)

    yerel_api.write_env(launch, path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "FT_YEREL_API=http://127.0.0.1:8765" in lines
    assert f"FT_YEREL_KOKEN={yerel_api.ORIGIN}" in lines
    assert f"FT_YEREL_JETON={launch.token}" in lines
    assert "eski" not in lines


class FakeServer:
    started: ClassVar[list[object]] = []

    def __init__(self, config: object) -> None:
        self.config = config

    def run(self) -> None:
        FakeServer.started.append(self.config)


def test_main_serves_on_loopback_and_writes_the_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeServer.started = []
    env = tmp_path / ".env.local"
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setattr(yerel_api, "ENV_FILE", env)
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))

    yerel_api.main(["--port", "8799"])

    (config,) = FakeServer.started
    assert isinstance(config, uvicorn.Config)
    assert (config.host, config.port, config.lifespan, config.proxy_headers) == (
        "127.0.0.1",
        8799,
        "on",
        False,
    )
    assert "FT_YEREL_API=http://127.0.0.1:8799" in env.read_text(encoding="utf-8")
    assert "npm run dev" in capsys.readouterr().out
