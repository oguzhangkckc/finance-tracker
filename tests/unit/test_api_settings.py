"""API ayarları (K-136): yalnız API ister ve denetler; ft bu ayarlardan etkilenmez."""

from pathlib import Path

import pytest

from finans.settings import (
    ApiSettings,
    ApiSettingsError,
    api_settings,
    load_base_settings,
    load_settings,
)

# Geçersiz olduğu denetlenen değer; hiçbir şey bu adrese bağlanmaz.
ALL_INTERFACES = "0.0.0.0"  # noqa: S104
VALID = {
    "FT_WEB_PORT": "8765",
    "FT_CF_ACCESS_TEAM_DOMAIN": "xht-takim.cloudflareaccess.com",
    "FT_CF_ACCESS_AUD": "xht-aud-0123456789abcdef",
    "FT_WEB_ALLOWED_EMAIL": "kullanici@example.com",
    "FT_WEB_ORIGIN": "https://finans.example.com",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def problems() -> str:
    with pytest.raises(ApiSettingsError) as caught:
        api_settings(load_base_settings())
    return str(caught.value)


def test_a_complete_environment_gives_the_api_settings(env: pytest.MonkeyPatch) -> None:
    assert api_settings(load_base_settings()) == ApiSettings(
        host="127.0.0.1",
        port=8765,
        team_domain="xht-takim.cloudflareaccess.com",
        audience="xht-aud-0123456789abcdef",
        allowed_email="kullanici@example.com",
        origin="https://finans.example.com",
    )


def test_values_are_trimmed_and_normalized(env: pytest.MonkeyPatch) -> None:
    env.setenv("FT_WEB_HOST", " ::1 ")
    env.setenv("FT_WEB_PORT", " 8765 ")
    env.setenv("FT_CF_ACCESS_TEAM_DOMAIN", " XHT-Takim.CloudflareAccess.com ")
    env.setenv("FT_WEB_ORIGIN", "https://Finans.Example.com:8443/")
    settings = api_settings(load_base_settings())

    assert (settings.host, settings.port, settings.team_domain, settings.origin) == (
        "::1",
        8765,
        "xht-takim.cloudflareaccess.com",
        "https://finans.example.com:8443",
    )


def test_every_missing_setting_is_reported_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    message = problems()

    assert message.startswith("API başlamaz (K-136): ")
    assert [name for name in VALID if name in message] == list(VALID)
    assert "FT_WEB_HOST" not in message


def test_blank_values_count_as_missing(env: pytest.MonkeyPatch) -> None:
    for name in VALID:
        env.setenv(name, "  ")
    assert [name for name in VALID if name in problems()] == list(VALID)


@pytest.mark.parametrize(
    "host", [ALL_INTERFACES, "10.0.0.5", "::", "fe80::1", "localhost", "finans.example.com"]
)
def test_only_a_loopback_address_can_be_the_host(env: pytest.MonkeyPatch, host: str) -> None:
    env.setenv("FT_WEB_HOST", host)
    assert "FT_WEB_HOST yalnız loopback adresi olabilir" in problems()


@pytest.mark.parametrize("port", ["0", "65536", "123456", "80a", "-1", "٣٣"])
def test_the_port_is_a_number_from_1_to_65535(env: pytest.MonkeyPatch, port: str) -> None:
    env.setenv("FT_WEB_PORT", port)
    assert "FT_WEB_PORT 1 ile 65535 arasında bir sayı olmalı" in problems()


@pytest.mark.parametrize(
    "domain",
    [
        "xht.example.com",
        "xht.cloudflareaccess.com.example.com",
        "https://xht.cloudflareaccess.com",
        "xht.cloudflareaccess.com/yol",
        "a.b.cloudflareaccess.com",
        "-xht.cloudflareaccess.com",
        "cloudflareaccess.com",
    ],
)
def test_keys_can_only_come_from_a_cloudflare_access_team_domain(
    env: pytest.MonkeyPatch, domain: str
) -> None:
    env.setenv("FT_CF_ACCESS_TEAM_DOMAIN", domain)
    assert "FT_CF_ACCESS_TEAM_DOMAIN <takım>.cloudflareaccess.com biçiminde olmalı" in problems()


@pytest.mark.parametrize("audience", ["xht aud", "xht\taud", "xht-aüd"])
def test_the_audience_is_a_single_ascii_word(env: pytest.MonkeyPatch, audience: str) -> None:
    env.setenv("FT_CF_ACCESS_AUD", audience)
    assert "FT_CF_ACCESS_AUD" in problems()


@pytest.mark.parametrize(
    "email", ["kullanici", "kullanici@", "@example.com", "a b@example.com", "kullanici@example"]
)
def test_the_allowed_email_looks_like_an_address(env: pytest.MonkeyPatch, email: str) -> None:
    env.setenv("FT_WEB_ALLOWED_EMAIL", email)
    assert "FT_WEB_ALLOWED_EMAIL bir e-posta adresi olmalı" in problems()


@pytest.mark.parametrize(
    "origin",
    [
        "http://finans.example.com",
        "https://finans.example.com/yol",
        "https://u:p@finans.example.com",
        "https://finans.example.com?a=1",
        "https://finans.example.com#x",
        "https://finans.example.com:abc",
        "finans.example.com",
        "https://",
    ],
)
def test_the_origin_is_https_without_a_path(env: pytest.MonkeyPatch, origin: str) -> None:
    env.setenv("FT_WEB_ORIGIN", origin)
    assert "FT_WEB_ORIGIN https://<alan adı> biçiminde olmalı" in problems()


def test_the_message_holds_no_values(env: pytest.MonkeyPatch) -> None:
    env.setenv("FT_WEB_ALLOWED_EMAIL", "gizli kisi@example.com")
    env.setenv("FT_CF_ACCESS_AUD", "gizli etiket")
    env.setenv("FT_WEB_HOST", "10.9.8.7")
    message = problems()
    assert "gizli" not in message
    assert "10.9.8.7" not in message


def test_ft_neither_needs_nor_checks_the_api_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_WEB_HOST", ALL_INTERFACES)
    monkeypatch.setenv("FT_WEB_PORT", "abc")
    monkeypatch.setenv("FT_CF_ACCESS_TEAM_DOMAIN", "kotu.example.com")
    settings = load_settings()

    assert (settings.web_host, settings.web_port) == (ALL_INTERFACES, "abc")


def test_blank_api_settings_are_undefined(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_WEB_PORT", "")
    monkeypatch.setenv("FT_WEB_ALLOWED_EMAIL", " ")
    settings = load_settings()

    assert (settings.web_port, settings.web_allowed_email) == (None, None)
