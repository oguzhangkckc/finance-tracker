import re
from pathlib import Path

import pytest

from finans.settings import Settings
from tests.support.web_profiles import ME, ORIGIN, PAGES, two_profiles, web

TOKEN = re.compile(r'name="belirtec" value="([0-9a-f]{64})"')


@pytest.fixture
def base(tmp_path: Path, migrated_db: Path) -> Settings:
    return two_profiles(tmp_path, migrated_db)


@pytest.mark.parametrize(("opening", "target"), [("real", "/gercek/"), ("sanal", "/sanal/")])
def test_root_goes_to_the_opening_profile(base: Settings, opening: str, target: str) -> None:
    response = web(base.model_copy(update={"profile": opening})).get("/", headers=ME)

    assert response.status_code == 307
    assert response.headers["location"] == target


def test_each_prefix_reads_its_own_database(base: Settings) -> None:
    client = web(base)

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
    client = web(base)

    for path in PAGES:
        page = client.get(f"/{slug}{path}", headers=ME)
        assert page.status_code == 200, (path, page.text)
        assert f'<html lang="tr" data-profile="{profile}">' in page.text, path
        assert ('class="band"' in page.text) is (profile == "sanal"), path


def test_the_profile_switch_keeps_the_page_and_links_stay_in_the_profile(base: Settings) -> None:
    page = web(base).get("/gercek/varliklar", headers=ME).text

    assert '<a href="/gercek/varliklar" aria-current="page">Gerçek</a>' in page
    assert '<a href="/sanal/varliklar">Sanal</a>' in page
    current = (
        r'<a href="/gercek/varliklar" aria-current="page"><svg[^>]*>.*?</svg><span>Varlıklar</span>'
    )
    assert len(re.findall(current, page, re.S)) == 2  # yan menü ve alt sekme
    assert 'href="/gercek/dagilim"' in page
    assert 'href="/sanal/dagilim"' not in page


@pytest.mark.parametrize("path", ["/baska/", "/varliklar", "/gercek/yok"])
def test_unknown_prefixes_and_unprefixed_pages_are_not_found(base: Settings, path: str) -> None:
    assert web(base).get(path, headers=ME).status_code == 404


@pytest.mark.parametrize(("slug", "profile"), [("gercek", "real"), ("sanal", "sanal")])
def test_a_refresh_request_goes_to_the_profile_of_the_page(
    base: Settings, slug: str, profile: str
) -> None:
    client = web(base)
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
