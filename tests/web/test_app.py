import logging
import socket
import stat
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import uvicorn

from finans.settings import Settings
from finans.web import __main__ as web_main
from finans.web.app import WebSetupError, create_app
from finans.web.security import SECURITY_HEADERS, display_name
from tests.support.web_client import WebClient

LOGIN = "kisi@example.com"
ORIGIN = "https://cihaz.ornek.ts.net"
ME = {"Tailscale-User-Login": LOGIN}
# Hayali ad: ğ, ö ve ç içerir; Tailscale bu başlığı RFC 2047 ile kodlar.
NAME = "Gökçe Doğan"
NAME_B = "=?utf-8?b?R8O2a8OnZSBEb8SfYW4=?="
NAME_Q = "=?utf-8?q?G=C3=B6k=C3=A7e_Do=C4=9Fan?="


def _settings(tmp_path: Path, **extra: object) -> Settings:
    values: dict[str, object] = {
        "db_path": tmp_path / "finans.db",
        "web_allowed_login": LOGIN,
        "web_origin": ORIGIN,
        **extra,
    }
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def client(tmp_path: Path) -> WebClient:
    return WebClient(create_app(_settings(tmp_path)))


def test_the_allowed_login_sees_the_page(client: WebClient) -> None:
    response = client.get("/", headers=ME)

    assert response.status_code == 200
    assert "<h1>Özet</h1>" in response.text
    assert LOGIN in response.text


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("Tailscale-User-Login", "")],
        [("Tailscale-User-Login", "baska@example.com")],
        [("Tailscale-User-Login", "Kisi@example.com")],
        [("Tailscale-User-Login", LOGIN), ("Tailscale-User-Login", LOGIN)],
    ],
)
def test_anything_but_exactly_one_allowed_login_is_refused(
    client: WebClient, headers: list[tuple[str, str]]
) -> None:
    response = client.get("/", headers=headers)

    assert response.status_code == 403
    assert response.text == "Erişim yok."


def test_identity_is_checked_before_routing(client: WebClient) -> None:
    assert client.get("/yok").status_code == 403
    assert client.get("/yok", headers=ME).status_code == 404


def test_the_display_name_never_grants_access(client: WebClient) -> None:
    headers = {"Tailscale-User-Login": "baska@example.com", "Tailscale-User-Name": NAME_Q}

    assert client.get("/", headers=headers).status_code == 403


@pytest.mark.parametrize("raw", [NAME_B, NAME_Q])
def test_an_rfc2047_display_name_is_decoded_for_the_page(client: WebClient, raw: str) -> None:
    response = client.get("/", headers={**ME, "Tailscale-User-Name": raw})

    assert display_name(raw) == NAME
    assert f'<span class="viewer">{NAME}</span>' in response.text


@pytest.mark.parametrize(
    "raw", [None, "", "=?utf-8?b?###?=", "=?bilinmeyen?q?x?=", "=?utf-8?q?=FF?="]
)
def test_an_undecodable_display_name_is_not_shown(client: WebClient, raw: str | None) -> None:
    headers = ME if raw is None else {**ME, "Tailscale-User-Name": raw}
    response = client.get("/", headers=headers)

    assert display_name(raw) is None
    assert f'<span class="viewer">{LOGIN}</span>' in response.text


def test_the_display_name_is_escaped(client: WebClient) -> None:
    response = client.get("/", headers={**ME, "Tailscale-User-Name": "<script>x</script>"})

    assert "<script>" not in response.text
    assert "&lt;script&gt;x&lt;/script&gt;" in response.text


@pytest.mark.parametrize("headers", [ME, {}])
def test_security_headers_are_on_every_response(client: WebClient, headers: dict[str, str]) -> None:
    response = client.get("/", headers=headers)

    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


async def _chunks() -> AsyncIterator[bytes]:
    yield b"a=1"


def test_only_reads_are_accepted(client: WebClient) -> None:
    assert client.head("/", headers=ME).status_code == 200
    assert client.post("/", headers=ME, content=b"a=1").status_code == 405
    assert client.post("/", headers=ME, content=b"x" * (16 * 1024 + 1)).status_code == 413
    chunked = client.post("/", headers=ME, content=_chunks())
    assert chunked.status_code == 411


def test_the_stylesheet_is_served(client: WebClient) -> None:
    response = client.get("/static/site.css", headers=ME)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize(("profile", "shown"), [("sanal", True), ("real", False)])
def test_the_sanal_profile_has_a_band_on_every_page(
    tmp_path: Path, profile: str, shown: bool
) -> None:
    page = WebClient(create_app(_settings(tmp_path, profile=profile))).get("/", headers=ME)

    assert ('class="band"' in page.text) is shown
    assert ("SANAL — gerçek alım değil" in page.text) is shown


@pytest.mark.parametrize("missing", ["web_allowed_login", "web_origin"])
def test_the_app_does_not_start_without_login_or_origin(tmp_path: Path, missing: str) -> None:
    with pytest.raises(WebSetupError, match="FT_WEB_ALLOWED_LOGIN ve FT_WEB_ORIGIN"):
        create_app(_settings(tmp_path, **{missing: ""}))


@pytest.fixture
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("_restore_logging")
def test_main_serves_only_on_the_owner_only_unix_socket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    served: list[list[socket.socket]] = []

    class FakeServer:
        def __init__(self, config: uvicorn.Config) -> None:
            assert config.proxy_headers is False

        def run(self, sockets: list[socket.socket]) -> None:
            served.append(sockets)

    with tempfile.TemporaryDirectory(prefix="ftw", dir="/tmp") as short:
        path = Path(short) / "web.sock"
        for name, value in {
            "FT_DB_PATH": str(tmp_path / "finans.db"),
            "FT_WEB_ALLOWED_LOGIN": LOGIN,
            "FT_WEB_ORIGIN": ORIGIN,
            "FT_WEB_SOCKET": str(path),
        }.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(uvicorn, "Server", FakeServer)

        web_main.main()

        [[listener]] = served
        try:
            assert listener.family == socket.AF_UNIX
            assert stat.S_IMODE(path.lstat().st_mode) == 0o600
        finally:
            listener.close()


def test_main_refuses_to_start_without_web_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))

    with pytest.raises(SystemExit) as stopped:
        web_main.main()

    assert stopped.value.code == 2
    assert "FT_WEB_ALLOWED_LOGIN ve FT_WEB_ORIGIN" in capsys.readouterr().err
