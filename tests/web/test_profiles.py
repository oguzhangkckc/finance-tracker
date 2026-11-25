import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finans import bootstrap
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.settings import Settings, profile_settings
from finans.web.app import create_app
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario
from tests.support.web_client import WebClient
from tests.web.test_pages import PORTFOLIO

LOGIN = "kisi@example.com"
ORIGIN = "https://cihaz.ornek.ts.net"
ME = {"Tailscale-User-Login": LOGIN}
# İstanbul'da Çarşamba 12:30: elle güncelleme açık.
NOW = FixedClock(datetime(2026, 11, 25, 9, 30, tzinfo=UTC))
PAGES = (
    "/",
    "/varliklar",
    "/dagilim",
    "/getiri",
    "/raporlar",
    "/raporlar/haftalik",
    "/raporlar/aylik",
    "/raporlar/maas-gunu",
    "/alarmlar",
    "/islemler",
    "/sistem",
)
TOKEN = re.compile(r'name="belirtec" value="([0-9a-f]{64})"')


@pytest.fixture
def base(tmp_path: Path, migrated_db: Path) -> Settings:
    """Gerçek veritabanında senaryonun işlemleri var; sanal veritabanı boş."""
    scenario.seed(migrated_db)
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    settings = Settings(
        db_path=migrated_db,
        portfolio_path=portfolio,
        web_allowed_login=LOGIN,
        web_origin=ORIGIN,
        web_session_key="k" * 64,
    )
    sanal = profile_settings(settings)["sanal"]
    bootstrap.sanal_init(sanal, NOW)
    with SqliteUnitOfWork(sanal.db_path, sanal=True) as uow:
        uow.instruments.sync(list(scenario.CONFIG.instruments))
    return settings


def _client(settings: Settings) -> WebClient:
    return WebClient(create_app(settings, clock=NOW))


@pytest.mark.parametrize(("opening", "target"), [("real", "/gercek/"), ("sanal", "/sanal/")])
def test_root_goes_to_the_opening_profile(base: Settings, opening: str, target: str) -> None:
    response = _client(base.model_copy(update={"profile": opening})).get("/", headers=ME)

    assert response.status_code == 307
    assert response.headers["location"] == target


def test_each_prefix_reads_its_own_database(base: Settings) -> None:
    client = _client(base)

    real = client.get("/gercek/islemler", headers=ME).text
    sanal = client.get("/sanal/islemler", headers=ME).text

    assert "<strong>XHT</strong>" in real
    assert "Kayıtlı işlem yok." not in real
    assert "<strong>XHT</strong>" not in sanal
    assert "Kayıtlı işlem yok." in sanal


@pytest.mark.parametrize(("slug", "profile"), [("gercek", "real"), ("sanal", "sanal")])
def test_every_page_carries_its_profile_and_only_sanal_has_the_band(
    base: Settings, slug: str, profile: str
) -> None:
    client = _client(base)

    for path in PAGES:
        page = client.get(f"/{slug}{path}", headers=ME)
        assert page.status_code == 200, (path, page.text)
        assert f'<html lang="tr" data-profile="{profile}">' in page.text, path
        assert ('class="band"' in page.text) is (profile == "sanal"), path


def test_the_profile_switch_keeps_the_page_and_links_stay_in_the_profile(base: Settings) -> None:
    page = _client(base).get("/gercek/varliklar", headers=ME).text

    assert '<a href="/gercek/varliklar" aria-current="page">Gerçek</a>' in page
    assert '<a href="/sanal/varliklar">Sanal</a>' in page
    assert '<a href="/gercek/varliklar" aria-current="page">Varlıklar</a>' in page
    assert 'href="/gercek/dagilim"' in page
    assert 'href="/sanal/dagilim"' not in page


@pytest.mark.parametrize("path", ["/baska/", "/varliklar", "/gercek/yok"])
def test_unknown_prefixes_and_unprefixed_pages_are_not_found(base: Settings, path: str) -> None:
    assert _client(base).get(path, headers=ME).status_code == 404


@pytest.mark.parametrize(("slug", "profile"), [("gercek", "real"), ("sanal", "sanal")])
def test_a_refresh_request_goes_to_the_profile_of_the_page(
    base: Settings, slug: str, profile: str
) -> None:
    client = _client(base)
    page = client.get(f"/{slug}/", headers=ME)
    match = TOKEN.search(page.text)
    assert match is not None
    cookie = page.headers["set-cookie"].split(";", 1)[0]

    response = client.post(
        f"/{slug}/fiyat-guncelle",
        headers={**ME, "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin", "Cookie": cookie},
        content=f"belirtec={match.group(1)}".encode(),
    )

    refresh = base.db_path.parent / "refresh"
    assert response.status_code == 303
    assert response.headers["location"] == f"/{slug}/?istek=alindi"
    assert sorted(p.name for p in refresh.glob("*.request")) == [f"{profile}.request"]
