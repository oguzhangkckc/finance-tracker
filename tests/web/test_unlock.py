"""Yazma kilidi sayfası ve üst çubuktaki durum etiketi (K-105, K-125, K-126)."""

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest

from finans.application.password import hash_password
from finans.settings import Settings
from finans.web.app import WebSetupError, create_app
from tests.fakes.clock import FixedClock
from tests.support.web_browser import LOGIN, ORIGIN, SAME_ORIGIN, SESSION_KEY, Browser
from tests.support.web_client import WebClient

PASSWORD = "uzun bir parola cümlesi"  # noqa: S105 - sahte test değeri
STORED = hash_password(PASSWORD)
WRONG = "yanlış bir parola cümlesi"


def _app(tmp_path: Path, stored: str | None = STORED) -> tuple[WebClient, FixedClock]:
    clock = FixedClock(datetime(2026, 12, 15, 9, 0, tzinfo=UTC))
    settings = Settings(
        db_path=tmp_path / "finans.db",
        web_allowed_login=LOGIN,
        web_origin=ORIGIN,
        web_session_key=SESSION_KEY,
        web_password=stored,
    )
    return WebClient(create_app(settings, clock=clock)), clock


def _chip(page: httpx.Response) -> str:
    match = re.search(r'<a class="lock[^"]*" href="([^"]+)">.*?</svg>([^<]+)</a>', page.text)
    assert match is not None, page.text
    return f"{match.group(2)} → {match.group(1)}"


def test_the_right_password_opens_writing_and_returns_to_the_page(tmp_path: Path) -> None:
    client, clock = _app(tmp_path)
    me = Browser(client)

    assert _chip(me.get("/gercek/daha")) == "Yazma kilitli → /gercek/kilit?sonra=/gercek/daha"
    form = me.get("/gercek/kilit?sonra=/gercek/islemler")
    assert f'name="belirtec" value="{me.token()}"' in form.text
    assert '<input type="hidden" name="sonra" value="/gercek/islemler">' in form.text
    assert 'type="password" autocomplete="current-password" required' in form.text

    response = me.unlock(PASSWORD)

    assert response.status_code == 303
    assert response.headers["location"] == "/gercek/islemler"
    assert _chip(me.get("/gercek/daha")).startswith("Yazma açık · 15 dk")
    clock.advance(timedelta(minutes=15))
    assert _chip(me.get("/gercek/daha")).startswith("Yazma kilitli")


def test_the_lock_is_per_session_and_shared_by_both_profiles(tmp_path: Path) -> None:
    client, _ = _app(tmp_path)
    me, other = Browser(client), Browser(client)

    assert me.unlock(PASSWORD, profile="sanal", sonra="/sanal/").status_code == 303

    assert _chip(me.get("/gercek/daha")).startswith("Yazma açık")
    assert _chip(me.get("/sanal/daha")).startswith("Yazma açık")
    assert _chip(other.get("/gercek/daha")).startswith("Yazma kilitli")


def test_wrong_passwords_count_down_and_the_fifth_closes_the_lock(tmp_path: Path) -> None:
    client, clock = _app(tmp_path)
    me = Browser(client)

    first = me.unlock(WRONG)
    assert first.status_code == 403
    assert "<strong>Şifre yanlış.</strong> 4 deneme hakkın kaldı" in first.text
    assert 'aria-invalid="true"' in first.text
    for _ in range(3):
        me.unlock(WRONG)

    fifth = me.unlock(WRONG)
    assert fifth.status_code == 429
    assert "Çok fazla yanlış deneme." in fifth.text
    assert "2026-12-15 12:15" in fifth.text
    assert me.unlock(PASSWORD).status_code == 429
    waiting = me.get("/gercek/kilit")
    assert "Çok fazla yanlış deneme." in waiting.text
    assert 'type="password"' not in waiting.text

    clock.advance(timedelta(minutes=15))
    assert me.unlock(PASSWORD).status_code == 303


@pytest.mark.parametrize(
    ("headers", "token"),
    [
        ({}, None),
        ({"Origin": "https://baska.ornek", "Sec-Fetch-Site": "cross-site"}, None),
        (SAME_ORIGIN, "0" * 64),
    ],
)
def test_a_cross_site_or_unsigned_attempt_is_refused_and_not_counted(
    tmp_path: Path, headers: dict[str, str], token: str | None
) -> None:
    client, _ = _app(tmp_path)
    me = Browser(client)

    for _ in range(5):
        assert me.unlock(WRONG, headers=headers, token=token).status_code == 403

    assert me.unlock(PASSWORD).status_code == 303


@pytest.mark.parametrize(
    "sonra",
    [
        "https://baska.ornek/",
        "//baska.ornek/",
        "/gercek/../../etc",
        "/gercek/islemler?x=1",
        "/baska/",
        "",
    ],
)
def test_only_local_pages_are_followed_after_unlocking(tmp_path: Path, sonra: str) -> None:
    client, _ = _app(tmp_path)
    me = Browser(client)

    form = me.get(f"/gercek/kilit?{urlencode({'sonra': sonra})}")
    assert '<input type="hidden" name="sonra" value="/gercek/">' in form.text
    assert me.unlock(PASSWORD, sonra=sonra).headers["location"] == "/gercek/"


def test_an_open_session_sees_how_long_writing_stays_open(tmp_path: Path) -> None:
    client, _ = _app(tmp_path)
    me = Browser(client)
    me.unlock(PASSWORD)

    page = me.get("/gercek/kilit?sonra=/gercek/islemler")

    assert "Yazma açık; kilit 15 dakika sonra kendiliğinden kapanır." in page.text
    assert '<a class="btn btn-primary" href="/gercek/islemler">Devam et</a>' in page.text
    assert 'type="password"' not in page.text


def test_without_a_hash_writing_is_not_set_up(tmp_path: Path) -> None:
    client, _ = _app(tmp_path, stored=None)
    me = Browser(client)

    assert _chip(me.get("/gercek/daha")).startswith("Yazma kapalı")
    page = me.get("/gercek/kilit")
    assert "Yazma bu cihazda kurulmadı." in page.text
    assert 'type="password"' not in page.text
    assert me.unlock(PASSWORD).status_code == 403


def test_a_malformed_hash_stops_the_web_from_starting(tmp_path: Path) -> None:
    with pytest.raises(WebSetupError, match="ft web sifre"):
        _app(tmp_path, stored="düz metin şifre")


def test_neither_the_password_nor_the_hash_reaches_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = _app(tmp_path)
    me = Browser(client)

    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            me.unlock(WRONG)
        me.unlock(PASSWORD)

    assert "Yazma kilidi 5 yanlış şifreden sonra 15 dakika kapatıldı." in caplog.messages
    logged = caplog.text
    assert WRONG not in logged
    assert PASSWORD not in logged
    assert STORED.split("$")[-1] not in logged
