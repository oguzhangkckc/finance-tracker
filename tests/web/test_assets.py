import hashlib
from pathlib import Path

import pytest

from finans.web.app import STATIC, create_app
from finans.web.assets import IMMUTABLE, Assets
from finans.web.security import SECURITY_HEADERS
from tests.support.web_client import WebClient
from tests.web.test_app import ME, _settings

DIGEST = hashlib.sha256((STATIC / "site.css").read_bytes()).hexdigest()[:12]
STYLESHEET = f"/static/site.{DIGEST}.css"


@pytest.fixture
def client(tmp_path: Path, migrated_db: Path) -> WebClient:
    return WebClient(create_app(_settings(tmp_path, db_path=migrated_db)))


def test_pages_link_the_stylesheet_by_its_content_digest(client: WebClient) -> None:
    page = client.get("/gercek/", headers=ME)

    assert f'<link rel="stylesheet" href="{STYLESHEET}">' in page.text
    assert page.headers["cache-control"] == "no-store"


def test_the_digested_stylesheet_is_cached_for_a_year(client: WebClient) -> None:
    response = client.get(STYLESHEET, headers=ME)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.headers["cache-control"] == IMMUTABLE
    assert response.content == (STATIC / "site.css").read_bytes()
    for name, value in SECURITY_HEADERS.items():
        if name != "Cache-Control":
            assert response.headers[name] == value


@pytest.mark.parametrize(
    "path",
    [
        "/static/site.css",
        "/static/site.000000000000.css",
        "/static/..%2Fapp.py",
        f"/static/yok.{DIGEST}.css",
    ],
)
def test_anything_but_a_current_digest_is_not_found(client: WebClient, path: str) -> None:
    response = client.get(path, headers=ME)

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


def test_static_files_also_need_the_allowed_login(client: WebClient) -> None:
    assert client.get(STYLESHEET).status_code == 403


def test_the_digest_follows_the_content(tmp_path: Path) -> None:
    (tmp_path / "a.css").write_text("x", encoding="utf-8")
    (tmp_path / "alt").mkdir()
    (tmp_path / "alt" / "b.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("l", encoding="utf-8")
    before = Assets(tmp_path)

    (tmp_path / "a.css").write_text("y", encoding="utf-8")
    after = Assets(tmp_path)

    digest = hashlib.sha256(b"x").hexdigest()[:12]
    assert before.url("a.css") == f"/static/a.{digest}.css"
    assert after.url("a.css") != before.url("a.css")
    assert after.url("alt/b.svg").startswith("/static/alt/b.")
    assert after.url("LICENSE").startswith("/static/LICENSE.")
