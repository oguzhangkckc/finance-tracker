"""Derlenmiş arayüzün sunulması (K-139): SPA, önbellek başlıkları, dizinin dışına çıkmama."""

from dataclasses import replace
from pathlib import Path

import pytest

from finans.api.app import create_app
from finans.api.middleware import SECURITY_HEADERS
from finans.api.static import IMMUTABLE, NOT_BUILT, PAGE_POLICY, REVALIDATE
from finans.settings import Settings
from tests.fakes.access import FakeAccessKeys
from tests.fakes.clock import FixedClock
from tests.support.access import API_SETTINGS
from tests.support.api_client import ApiClient

INDEX = '<!doctype html><title>finans</title><div id="root"></div>'
SCRIPT = "console.log('arayüz');"
ASSET = "/assets/index-AbC123.js"
OUTSIDE = "dizinin dışındaki dosya"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets" / "index-AbC123.js").write_text(SCRIPT, encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "disarida.txt").write_text(OUTSIDE, encoding="utf-8")
    return root


def site(
    root: Path, settings: Settings, clock: FixedClock, keys: FakeAccessKeys, *, signed: bool = True
) -> ApiClient:
    app = create_app(settings, replace(API_SETTINGS, dist=root), keys=keys, clock=clock)
    return ApiClient(app, clock, signed=signed)


@pytest.fixture
def web(dist: Path, settings: Settings, clock: FixedClock, keys: FakeAccessKeys) -> ApiClient:
    return site(dist, settings, clock, keys)


@pytest.mark.parametrize(
    "path", ["/", "/gercek", "/sanal/varliklar/lotlar", "/sanal/", "/index.html", "/docs"]
)
def test_a_page_address_gets_the_index_with_the_page_policy(web: ApiClient, path: str) -> None:
    response = web.get(path)

    assert (response.status_code, response.text) == (200, INDEX)
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == REVALIDATE
    assert response.headers["content-security-policy"] == PAGE_POLICY
    for name in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        assert response.headers[name] == SECURITY_HEADERS[name]


def test_hashed_assets_are_cached_for_a_year(web: ApiClient) -> None:
    response = web.get(ASSET)

    assert (response.status_code, response.text) == (200, SCRIPT)
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == IMMUTABLE
    assert (
        response.headers["content-security-policy"] == SECURITY_HEADERS["Content-Security-Policy"]
    )


def test_other_files_at_the_root_are_revalidated(web: ApiClient) -> None:
    response = web.get("/favicon.svg")

    assert (response.status_code, response.text) == (200, "<svg/>")
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == REVALIDATE
    assert response.headers["content-security-policy"] != PAGE_POLICY


@pytest.mark.parametrize("path", ["/assets/yok.js", "/assets/", "/assets"])
def test_a_missing_asset_is_404_not_the_index(web: ApiClient, path: str) -> None:
    response = web.get(path)

    assert (response.status_code, response.json()) == (404, {"error": "Bulunamadı.", "fields": {}})


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/disarida.txt",
        "/assets/%2e%2e/%2e%2e/disarida.txt",
        "/%2F" + "%2F".join(("etc", "passwd")),
        "/kopru.txt",
        "/x%00y",
    ],
)
def test_nothing_outside_the_directory_is_served(web: ApiClient, dist: Path, path: str) -> None:
    (dist / "kopru.txt").symlink_to(dist.parent / "disarida.txt")

    response = web.get(path)

    assert response.status_code == 404
    assert OUTSIDE not in response.text


def test_an_asset_address_that_leaves_assets_is_not_cached_as_an_asset(web: ApiClient) -> None:
    response = web.get("/assets/%2e%2e/index.html")

    assert (response.status_code, response.text) == (200, INDEX)
    assert response.headers["cache-control"] == REVALIDATE


def test_the_api_keeps_its_json_404_and_405(web: ApiClient) -> None:
    assert web.get("/api/yok").status_code == 404
    assert web.get("/api").status_code == 404
    assert web.get("/api/gercek/fiyat-guncelle").status_code == 405
    assert web.post("/api/oturum", json={}).status_code == 405


def test_api_responses_still_forbid_caching(web: ApiClient) -> None:
    response = web.get("/api/oturum")

    assert response.headers["cache-control"] == "no-store"
    assert (
        response.headers["content-security-policy"] == SECURITY_HEADERS["Content-Security-Policy"]
    )


def test_only_reads_are_served(web: ApiClient) -> None:
    response = web.post("/gercek", json={})

    assert (response.status_code, response.headers["allow"]) == (405, "GET, HEAD")


def test_head_sends_the_headers_without_the_page(web: ApiClient) -> None:
    response = web.request("HEAD", "/gercek")

    assert (response.status_code, response.content) == (200, b"")
    assert response.headers["content-security-policy"] == PAGE_POLICY


@pytest.mark.parametrize("path", ["/", ASSET, "/favicon.svg"])
def test_without_an_access_token_nothing_is_served(
    dist: Path, settings: Settings, clock: FixedClock, keys: FakeAccessKeys, path: str
) -> None:
    response = site(dist, settings, clock, keys, signed=False).get(path)

    assert response.status_code == 403
    assert INDEX not in response.text
    assert SCRIPT not in response.text


@pytest.mark.parametrize("build", ["missing", "no-index"])
def test_a_missing_build_is_an_explained_503(
    tmp_path: Path, settings: Settings, clock: FixedClock, keys: FakeAccessKeys, build: str
) -> None:
    root = tmp_path / "dist"
    if build == "no-index":
        (root / "assets").mkdir(parents=True)

    response = site(root, settings, clock, keys).get("/gercek")

    assert (response.status_code, response.json()) == (503, {"error": NOT_BUILT, "fields": {}})


def test_a_replaced_build_is_served_at_once(web: ApiClient, dist: Path) -> None:
    assert web.get("/").text == INDEX
    dist.rename(dist.with_name("dist.eski"))
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>yeni</title>", encoding="utf-8")

    assert web.get("/").text == "<!doctype html><title>yeni</title>"
