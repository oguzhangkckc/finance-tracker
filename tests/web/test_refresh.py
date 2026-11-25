import re
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.settings import Settings
from finans.web.app import create_app
from finans.web.session import SESSION_COOKIE, csrf_token
from tests.fakes.clock import FixedClock
from tests.support.web_client import WebClient

LOGIN = "kisi@example.com"
ORIGIN = "https://cihaz.ornek.ts.net"
SESSION_KEY = "k" * 64
ME = {"Tailscale-User-Login": LOGIN}
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
TOKEN = re.compile(r'name="belirtec" value="([0-9a-f]{64})"')
# İstanbul'da Çarşamba 12:30 ve Cumartesi 12:30.
WEDNESDAY = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)
SATURDAY = datetime(2026, 11, 28, 9, 30, tzinfo=UTC)
PORTFOLIO = """
[targets]
hisse = 1

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse"
"""


def _client(db: Path, now: datetime = WEDNESDAY) -> WebClient:
    portfolio = db.parent / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    settings = Settings(
        db_path=db,
        portfolio_path=portfolio,
        web_allowed_login=LOGIN,
        web_origin=ORIGIN,
        web_session_key=SESSION_KEY,
    )
    return WebClient(create_app(settings, clock=FixedClock(now)))


def _open(client: WebClient) -> tuple[str, str]:
    page = client.get("/", headers=ME)
    match = TOKEN.search(page.text)
    assert match is not None, page.text
    return page.headers["set-cookie"].split(";", 1)[0], match.group(1)


def _signed_session(client: WebClient) -> tuple[str, str, str]:
    """Düğme kapalıyken sayfada belirteç yok; isteği yine de gönderip reddini görmek için."""
    page = client.get("/", headers=ME)
    cookie = page.headers["set-cookie"].split(";", 1)[0]
    session = cookie.split("=", 1)[1].split(".", 1)[0]
    return page.text, cookie, csrf_token(SESSION_KEY.encode(), session)


def _post(
    client: WebClient, cookie: str, body: str, headers: dict[str, str] = SAME_ORIGIN
) -> httpx.Response:
    return client.post(
        "/fiyat-guncelle",
        headers={
            **ME,
            **headers,
            "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        content=body.encode(),
    )


def test_the_session_cookie_is_host_only_strict_and_kept(migrated_db: Path) -> None:
    client = _client(migrated_db)

    first = client.get("/", headers=ME)
    cookie = first.headers["set-cookie"]
    again = client.get("/", headers={**ME, "Cookie": cookie.split(";", 1)[0]})

    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert cookie.endswith("; Path=/; Secure; HttpOnly; SameSite=Strict")
    assert "set-cookie" not in again.headers
    assert TOKEN.findall(again.text) == TOKEN.findall(first.text)


def test_an_accepted_request_leaves_the_file_and_closes_the_button(migrated_db: Path) -> None:
    client = _client(migrated_db)
    cookie, token = _open(client)

    response = _post(client, cookie, f"belirtec={token}")

    assert response.status_code == 303
    assert response.headers["location"] == "/?istek=alindi"
    request = migrated_db.parent / "refresh" / "real.request"
    assert request.read_text(encoding="utf-8") == f"{WEDNESDAY.isoformat()}\n"
    after = client.get("/?istek=alindi", headers={**ME, "Cookie": cookie})
    assert "Güncelleme isteği alındı" in after.text
    assert 'action="/fiyat-guncelle"' not in after.text
    assert (
        "Elle güncelleme şu an kapalı: son güncellemeden bu yana 1 saat geçmedi. "
        "En erken 2026-11-25 13:30."
    ) in after.text


OTHER_SESSION = csrf_token(SESSION_KEY.encode(), "baska-oturum")


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({"Sec-Fetch-Site": "same-origin"}, "belirtec={token}"),
        ({"Origin": "null", "Sec-Fetch-Site": "same-origin"}, "belirtec={token}"),
        (
            {"Origin": "https://baska.ornek.ts.net", "Sec-Fetch-Site": "same-origin"},
            "belirtec={token}",
        ),
        ({"Origin": ORIGIN}, "belirtec={token}"),
        ({"Origin": ORIGIN, "Sec-Fetch-Site": "same-site"}, "belirtec={token}"),
        ({"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}, "belirtec={token}"),
        (SAME_ORIGIN, ""),
        (SAME_ORIGIN, "belirtec=" + "0" * 64),
        (SAME_ORIGIN, f"belirtec={OTHER_SESSION}"),
        (SAME_ORIGIN, "belirtec={token}&belirtec={token}"),
        (SAME_ORIGIN, "belirtec=%C3%A7"),
    ],
    ids=[
        "origin-yok",
        "origin-null",
        "baska-origin",
        "fetch-metadata-yok",
        "same-site",
        "cross-site",
        "belirtec-yok",
        "yanlis-belirtec",
        "baska-oturumun-belirteci",
        "iki-belirtec",
        "ascii-disi-belirtec",
    ],
)
def test_forged_requests_are_refused_and_leave_no_file(
    migrated_db: Path, headers: dict[str, str], body: str
) -> None:
    client = _client(migrated_db)
    cookie, token = _open(client)

    response = _post(client, cookie, body.format(token=token), headers)

    assert response.status_code == 403
    assert response.text == "İstek reddedildi."
    assert not (migrated_db.parent / "refresh").exists()


def test_an_unsigned_cookie_does_not_carry_a_session(migrated_db: Path) -> None:
    client = _client(migrated_db)
    forged = "saldirgan-oturumu"
    token = csrf_token(SESSION_KEY.encode(), forged)

    response = _post(client, f"{SESSION_COOKIE}={forged}.imzasiz", f"belirtec={token}")

    assert response.status_code == 403
    assert response.headers["set-cookie"].startswith(f"{SESSION_COOKIE}=")
    assert not (migrated_db.parent / "refresh").exists()


@pytest.mark.parametrize("body", [b"belirtec=\xff", b"a=1&b=2&c=3&d=4&e=5"])
def test_an_unreadable_form_is_rejected(migrated_db: Path, body: bytes) -> None:
    client = _client(migrated_db)
    cookie, _ = _open(client)

    response = client.post(
        "/fiyat-guncelle", headers={**ME, **SAME_ORIGIN, "Cookie": cookie}, content=body
    )

    assert response.status_code == 400
    assert response.text == "Form okunamadı."


def test_weekends_close_the_button_and_refuse_the_request(migrated_db: Path) -> None:
    client = _client(migrated_db, SATURDAY)
    page, cookie, token = _signed_session(client)

    response = _post(client, cookie, f"belirtec={token}")

    assert 'action="/fiyat-guncelle"' not in page
    assert (
        "Elle güncelleme şu an kapalı: hafta sonu fiyat yayımlanmaz. En erken 2026-11-30 00:00."
    ) in page
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert not (migrated_db.parent / "refresh" / "real.request").exists()


def test_the_daily_limit_refuses_without_touching_the_log(migrated_db: Path) -> None:
    log = migrated_db.parent / "refresh" / "real.log"
    log.parent.mkdir()
    six = "".join(f"2026-11-25T0{hour}:00:00+03:00\n" for hour in range(6))
    log.write_text(six, encoding="utf-8")
    client = _client(migrated_db)
    page, cookie, token = _signed_session(client)

    response = _post(client, cookie, f"belirtec={token}")

    assert "bugünkü 6 elle güncelleme kullanıldı. En erken 2026-11-26 00:00." in page
    assert response.headers["location"] == "/"
    assert log.read_text(encoding="utf-8") == six
    assert not (log.parent / "real.request").exists()


def test_the_last_price_sync_is_shown_and_starts_the_wait(migrated_db: Path) -> None:
    synced = datetime(2026, 11, 25, 9, 15, tzinfo=UTC)
    with SqliteUnitOfWork(migrated_db) as uow:
        run = uow.runs.start("sync-prices", date(2026, 11, 25), at=synced)
        uow.runs.finish(run, "ok", "{}", at=synced)

    page = _client(migrated_db).get("/", headers=ME)

    assert "Son fiyat güncellemesi: 2026-11-25 12:15" in page.text
    assert "En erken 2026-11-25 13:15." in page.text


def test_an_unwritable_request_directory_is_reported(migrated_db: Path) -> None:
    (migrated_db.parent / "refresh").write_text("dizin değil", encoding="utf-8")
    client = _client(migrated_db)
    cookie, token = _open(client)

    response = _post(client, cookie, f"belirtec={token}")

    assert response.status_code == 503
    assert "Güncelleme isteği yazılamadı; /sistem sayfasına bakın." in response.text
