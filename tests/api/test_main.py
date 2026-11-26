"""finans-api giriş noktası (K-136): yalnız loopback adresinde, ayarlar eksikse açılmaz."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from finans.api import __main__ as api_main

API_ENV = {
    "FT_WEB_PORT": "8765",
    "FT_CF_ACCESS_TEAM_DOMAIN": "xht-takim.cloudflareaccess.com",
    "FT_CF_ACCESS_AUD": "xht-aud-0123456789abcdef",
    "FT_WEB_ALLOWED_EMAIL": "kullanici@example.com",
    "FT_WEB_ORIGIN": "https://finans.example.com",
    "FT_WEB_SESSION_KEY": "k" * 64,
}


@pytest.fixture
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("_restore_logging")
def test_main_serves_on_the_loopback_address_and_fetches_keys_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configs: list[uvicorn.Config] = []
    runs: list[bool] = []

    class FakeServer:
        def __init__(self, config: uvicorn.Config) -> None:
            configs.append(config)

        def run(self) -> None:
            runs.append(True)

    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    for name, value in API_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    api_main.main()

    [config] = configs
    assert (config.host, config.port, config.lifespan) == ("127.0.0.1", 8765, "on")
    assert (config.proxy_headers, config.server_header, config.access_log) == (False, False, False)
    assert config.log_config is None
    assert runs == [True]


def test_main_refuses_to_start_without_the_api_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    error = capsys.readouterr().err
    assert stopped.value.code == 2
    assert error.startswith("finans-api başlamadı: API başlamaz (K-136): ")
    assert "FT_CF_ACCESS_AUD" in error
    assert "Traceback" not in error


def test_main_refuses_to_start_with_broken_base_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in API_ENV.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    assert stopped.value.code == 2
    assert capsys.readouterr().err == "finans-api başlamadı: Ayarlar eksik ya da geçersiz.\n"
