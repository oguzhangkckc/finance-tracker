import json

import httpx
import pytest
import respx

from finans import bootstrap
from finans.adapters._http import USER_AGENT
from finans.adapters.cf_access import MAX_BYTES, CloudflareAccessKeys
from finans.ports.access import AccessKeyError
from tests.support.access import API_SETTINGS, TEAM_DOMAIN, public_jwk

URL = f"https://{TEAM_DOMAIN}/cdn-cgi/access/certs"


def fetch_error() -> str:
    with pytest.raises(AccessKeyError) as caught:
        CloudflareAccessKeys(TEAM_DOMAIN).fetch()
    return str(caught.value)


@respx.mock
def test_keys_come_from_the_team_address_with_a_five_second_timeout() -> None:
    key = public_jwk()
    route = respx.get(URL).mock(
        return_value=httpx.Response(200, json={"keys": [key], "public_cert": {"kid": "x"}})
    )

    assert CloudflareAccessKeys(TEAM_DOMAIN).fetch() == (key,)
    request = route.calls.last.request
    assert request.headers["User-Agent"] == USER_AGENT
    assert request.headers["Accept"] == "application/json"
    assert request.extensions["timeout"] == {"connect": 5, "read": 5, "write": 5, "pool": 5}


def test_bootstrap_wires_the_configured_team_address() -> None:
    source = bootstrap.access_keys(API_SETTINGS)
    assert isinstance(source, CloudflareAccessKeys)
    assert source.url == URL


@respx.mock
def test_an_empty_key_list_is_returned_as_is() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"keys": []}))
    assert CloudflareAccessKeys(TEAM_DOMAIN).fetch() == ()


@respx.mock
def test_an_error_status_is_a_fetch_error() -> None:
    respx.get(URL).mock(return_value=httpx.Response(503))
    assert fetch_error() == "HTTP 503"


@respx.mock
def test_a_redirect_is_not_followed() -> None:
    elsewhere = respx.get("https://baska.example.com/certs").mock(
        return_value=httpx.Response(200, json={"keys": [public_jwk("baska")]})
    )
    respx.get(URL).mock(
        return_value=httpx.Response(302, headers={"Location": "https://baska.example.com/certs"})
    )

    assert fetch_error() == "HTTP 302"
    assert not elsewhere.called


@respx.mock
@pytest.mark.parametrize(
    "error", [httpx.ConnectError("yok"), httpx.ReadTimeout("geç"), httpx.ConnectTimeout("geç")]
)
def test_a_network_failure_is_a_fetch_error(error: httpx.HTTPError) -> None:
    respx.get(URL).mock(side_effect=error)
    assert fetch_error() == type(error).__name__


@respx.mock
def test_an_oversized_answer_is_refused() -> None:
    body = json.dumps({"keys": [public_jwk()], "dolgu": "x" * MAX_BYTES}).encode()
    respx.get(URL).mock(return_value=httpx.Response(200, content=body))
    assert fetch_error() == f"yanıt {MAX_BYTES} baytı aşıyor"


@respx.mock
@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"<html></html>", "yanıt JSON değil"),
        (b"[]", "yanıtta anahtar listesi yok"),
        (b'{"anahtarlar": []}', "yanıtta anahtar listesi yok"),
        (b'{"keys": {}}', "yanıtta anahtar listesi yok"),
        (b'{"keys": ["metin"]}', "yanıtta anahtar listesi yok"),
    ],
)
def test_an_answer_without_a_key_list_is_a_fetch_error(content: bytes, reason: str) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=content))
    assert fetch_error() == reason
