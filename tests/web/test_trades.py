"""Web'den işlem girişi ve iptal: önizleme yazmaz, kayıt önizlemenin aynısıdır, onay imzalı ve
tek kullanımlıktır (K-105, K-116, K-125, K-126)."""

import logging
import re
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.password import hash_password
from finans.cli.main import app as ft_app
from finans.domain.models import PricePoint, Side, Transaction
from finans.ports.repositories import StoredTransaction
from finans.settings import Profile, Settings, profile_settings
from finans.web.app import create_app
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario
from tests.support.web_browser import Browser, hidden_fields
from tests.support.web_client import WebClient
from tests.support.web_profiles import two_profiles

PASSWORD = "uzun bir parola cümlesi"  # noqa: S105 - sahte test değeri
STORED = hash_password(PASSWORD)
# İstanbul'da Çarşamba 12:30; senaryonun 25 Kasım fiyatları kayıtlı, XHT'de 110 pay var.
NOW = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)
GERCEK = "<strong>GERÇEK</strong> portföye kaydedilecek."
SANAL = "<strong>SANAL</strong> portföye kaydedilecek."
REAL_BUY = {
    "fon": "XHT",
    "gun": "2026-11-25",
    "adet": "10",
    "fiyat": "11,000000",
    "komisyon": "0",
    "dekont": "D-1",
}
SLUG: dict[Profile, str] = {"real": "gercek", "sanal": "sanal"}


@dataclass
class Site:
    settings: Settings
    clock: FixedClock
    client: WebClient

    def conf(self, profile: Profile) -> Settings:
        return profile_settings(self.settings)[profile]

    def rows(self, profile: Profile) -> list[StoredTransaction]:
        conf = self.conf(profile)
        with SqliteUnitOfWork(conf.db_path, readonly=True, sanal=profile == "sanal") as uow:
            return uow.transactions.list(include_voided=True)

    def browser(self, *, unlocked: bool = True) -> Browser:
        me = Browser(self.client)
        if unlocked:
            assert me.unlock(PASSWORD).status_code == 303
        return me


def _priced_sanal(sanal: Settings) -> None:
    with SqliteUnitOfWork(sanal.db_path, sanal=True) as uow:
        for day, prices in scenario.PRICES.items():
            for code, price in prices.items():
                point = PricePoint(code, day, Decimal(price), "tefas")
                uow.prices.upsert(point, fetched_at=scenario.PRICE_FETCH)


def _site(tmp_path: Path, db: Path, *, stored: str | None = STORED) -> Site:
    settings = two_profiles(tmp_path, db)
    if stored is not None:
        settings = settings.model_copy(update={"web_password": SecretStr(stored)})
    _priced_sanal(profile_settings(settings)["sanal"])
    clock = FixedClock(NOW)
    return Site(settings, clock, WebClient(create_app(settings, clock=clock)))


@pytest.fixture
def site(tmp_path: Path, migrated_db: Path) -> Site:
    return _site(tmp_path, migrated_db)


def _preview(me: Browser, profile: Profile, kind: str, data: dict[str, str]) -> httpx.Response:
    return me.post(f"/{SLUG[profile]}/islemler/yeni/{kind}", data)


def _confirm(me: Browser, profile: Profile, preview: httpx.Response) -> httpx.Response:
    action = f"/{SLUG[profile]}/islemler/kaydet"
    return me.post(action, hidden_fields(preview.text, action))


def _same_row(stored: StoredTransaction) -> tuple[object, ...]:
    """Ondalıkların girilen basamakları da aynı olmalı (K-64)."""
    tx = stored.transaction
    scales = tuple(value.as_tuple() for value in (tx.units, tx.unit_price, tx.fee))
    return (tx, scales, stored.external_ref, stored.note, stored.voided_at)


def _cli_twin(tmp_path: Path) -> Settings:
    """Aynı senaryoyla kurulmuş ikinci bir veritabanı; CLI eşlik testi oraya yazar."""
    db = tmp_path / "cli" / "finans.db"
    db.parent.mkdir()
    with closing(connect(db)) as conn:
        apply(conn, bundled(), clock=FixedClock(NOW))
    settings = two_profiles(db.parent, db)
    _priced_sanal(profile_settings(settings)["sanal"])
    return settings


def _cli(settings: Settings, profile: Profile, args: list[str], mp: pytest.MonkeyPatch) -> None:
    mp.setenv("FT_DB_PATH", str(settings.db_path))
    mp.setenv("FT_SANAL_DB_PATH", str(settings.sanal_database))
    mp.setenv("FT_PROFILE", profile)
    result = CliRunner().invoke(ft_app, args)
    assert result.exit_code == 0, result.output


def _cli_rows(settings: Settings, profile: Profile) -> list[StoredTransaction]:
    conf = profile_settings(settings)[profile]
    with SqliteUnitOfWork(conf.db_path, readonly=True, sanal=profile == "sanal") as uow:
        return uow.transactions.list(include_voided=True)


def test_a_real_buy_is_previewed_without_writing_and_saved_as_the_cli_would(
    site: Site, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = site.browser()
    form = me.get("/gercek/islemler/yeni/alis")
    assert form.status_code == 200
    assert '<label for="dekont">Dekont no' in form.text
    hint = "Aynı dekontun iki kez girilmesini engeller, ekstre mutabakatını kolaylaştırır."
    assert hint in form.text
    assert 'name="tutar"' not in form.text

    preview = _preview(me, "real", "alis", REAL_BUY)
    assert preview.status_code == 200, preview.text
    assert GERCEK in preview.text
    assert SANAL not in preview.text
    assert "Gerçek alımı kaydet" in preview.text
    assert "11,000000 TL" in preview.text
    assert "110 → 120" in preview.text
    assert len(site.rows("real")) == len(scenario.TRADES)

    saved = _confirm(me, "real", preview)

    assert saved.status_code == 303
    assert saved.headers["location"] == "/gercek/islemler?islem=alis&no=5"
    assert "Alım #5 kaydedildi." in me.get(saved.headers["location"]).text
    twin = _cli_twin(tmp_path)
    args = ["tx", "add", "buy", "XHT", "10", "11.000000", "--date", "2026-11-25", "--ref", "D-1"]
    _cli(twin, "real", args, monkeypatch)
    assert _same_row(site.rows("real")[-1]) == _same_row(_cli_rows(twin, "real")[-1])


def test_a_sanal_buy_by_amount_and_a_sale_of_everything_match_the_cli(
    site: Site, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = site.browser()
    form = me.get("/sanal/islemler/yeni/alis")
    assert 'name="tutar"' in form.text
    assert 'name="fiyat"' not in form.text
    assert 'name="dekont"' not in form.text

    preview = _preview(me, "sanal", "alis", {"fon": "XHT", "gun": "2026-11-25", "tutar": "1000"})
    assert preview.status_code == 200, preview.text
    assert SANAL in preview.text
    assert GERCEK not in preview.text
    assert "Sanal alımı kaydet" in preview.text
    assert 'class="notice warn"' not in preview.text
    assert 'class="notice info"' not in preview.text
    assert "90 pay" in preview.text
    assert "990,00 TL" in preview.text
    assert _confirm(me, "sanal", preview).headers["location"] == "/sanal/islemler?islem=alis&no=1"

    sell = _preview(me, "sanal", "satis", {"fon": "XHT", "gun": "2026-11-25", "tumu": "1"})
    assert "90 → 0" in sell.text
    assert _confirm(me, "sanal", sell).status_code == 303

    twin = _cli_twin(tmp_path)
    _cli(
        twin,
        "sanal",
        ["sanal", "al", "XHT", "--tutar", "1000", "--tarih", "2026-11-25"],
        monkeypatch,
    )
    _cli(twin, "sanal", ["sanal", "sat", "XHT", "90", "--tarih", "2026-11-25"], monkeypatch)
    web, cli = site.rows("sanal"), _cli_rows(twin, "sanal")
    assert [_same_row(s) for s in web] == [_same_row(s) for s in cli]


def test_the_real_form_has_no_amount_buy_and_the_sanal_form_no_receipt(site: Site) -> None:
    me = site.browser()

    real = me.get("/gercek/islemler/yeni/satis").text
    sanal = me.get("/sanal/islemler/yeni/satis").text

    assert 'name="tumu"' not in real
    assert 'name="fiyat"' in real
    assert 'name="tumu"' in sanal
    assert 'name="fiyat"' not in sanal


def test_the_same_confirmation_twice_shows_the_first_record(site: Site) -> None:
    me = site.browser()
    preview = _preview(me, "real", "alis", REAL_BUY)
    first = _confirm(me, "real", preview)

    second = _confirm(me, "real", preview)

    assert first.status_code == 303
    assert second.status_code == 409
    assert "Bu onay zaten kullanıldı; işlem #5 olarak kaydedildi." in second.text
    assert len(site.rows("real")) == len(scenario.TRADES) + 1


def test_a_change_after_the_preview_shows_a_new_preview_and_saves_nothing(site: Site) -> None:
    me = site.browser()
    preview = _preview(me, "real", "satis", {**REAL_BUY, "adet": "100", "dekont": "", "fon": "XHT"})
    assert "110 → 10" in preview.text
    with SqliteUnitOfWork(site.conf("real").db_path) as uow:
        sale = Transaction("XHT", NOW.date(), Side.SELL, Decimal(5), Decimal("11.000000"))
        uow.transactions.add(sale, external_ref=None, note=None, created_at=NOW)

    changed = _confirm(me, "real", preview)

    assert changed.status_code == 409
    assert "Önizlemeden sonra veriler değişti; kayıt yapılmadı." in changed.text
    assert "105 → 5" in changed.text
    assert len(site.rows("real")) == len(scenario.TRADES) + 1
    assert _confirm(me, "real", changed).status_code == 303


@pytest.mark.parametrize(
    ("change", "field", "message"),
    [
        (
            {"fiyat": "11.5"},
            "fiyat",
            "Birim fiyat: nokta kullanılmaz; ondalık ayırıcı virgüldür (1,5), "
            "binlik ayırıcı yazılmaz (5000).",
        ),
        ({"adet": "0"}, "adet", "Adet sıfırdan büyük olmalı."),
        ({"gun": "25.11.2026"}, "gun", "Tarih YYYY-AA-GG biçiminde olmalı, '25.11.2026' verildi."),
        ({"fon": ""}, "fon", "Fon seç."),
    ],
)
def test_form_errors_keep_the_values_and_say_what_to_fix(
    site: Site, change: dict[str, str], field: str, message: str
) -> None:
    me = site.browser()

    page = _preview(me, "real", "alis", {**REAL_BUY, **change})

    assert page.status_code == 400
    assert message.replace("'", "&#39;") in page.text
    assert re.search(rf'id="{field}"[^>]*aria-invalid="true"', page.text)
    assert 'value="D-1"' in page.text
    assert len(site.rows("real")) == len(scenario.TRADES)


@pytest.mark.parametrize(
    ("profile", "kind", "data", "message"),
    [
        ("real", "satis", {**REAL_BUY, "adet": "1000", "dekont": ""}, "1000 adet satılmak"),
        (
            "sanal",
            "alis",
            {"fon": "XHT", "gun": "2026-11-24", "tutar": "1000"},
            "tarihli fiyat yok",
        ),
        ("sanal", "satis", {"fon": "XHT", "gun": "2026-11-25", "tumu": "1"}, "elde pay yok"),
    ],
)
def test_refusals_from_the_shared_rules_show_on_the_form(
    site: Site, profile: Profile, kind: str, data: dict[str, str], message: str
) -> None:
    me = site.browser()

    page = _preview(me, profile, kind, data)

    assert page.status_code == 400
    assert '<div class="notice error" role="alert">' in page.text
    assert message in page.text


def test_a_repeated_receipt_number_is_refused_before_saving(site: Site) -> None:
    me = site.browser()
    _confirm(me, "real", _preview(me, "real", "alis", REAL_BUY))

    again = _preview(me, "real", "alis", REAL_BUY)

    assert again.status_code == 400
    assert "D-1 ref&#39;li etkin bir işlem zaten var." in again.text


def test_a_price_that_differs_from_tefas_warns_but_can_be_saved(site: Site) -> None:
    me = site.browser()

    preview = _preview(me, "real", "alis", {**REAL_BUY, "fiyat": "11,500000"})

    assert preview.status_code == 200
    assert '<div class="notice warn" role="status">' in preview.text
    assert _confirm(me, "real", preview).status_code == 303


@pytest.mark.parametrize(
    ("tamper", "status", "text"),
    [
        (lambda f: {**f, "adet": "11"}, 403, "İstek reddedildi."),
        (lambda f: {**f, "imza": "0" * 64}, 403, "İstek reddedildi."),
        (lambda f: {k: v for k, v in f.items() if k != "imza"}, 403, "İstek reddedildi."),
    ],
)
def test_a_tampered_confirmation_is_refused(
    site: Site, tamper: Callable[[dict[str, str]], dict[str, str]], status: int, text: str
) -> None:
    me = site.browser()
    preview = _preview(me, "real", "alis", REAL_BUY)
    fields = hidden_fields(preview.text, "/gercek/islemler/kaydet")

    response = me.post("/gercek/islemler/kaydet", tamper(fields))

    assert response.status_code == status
    assert text in response.text
    assert len(site.rows("real")) == len(scenario.TRADES)


def test_a_confirmation_from_another_session_or_profile_is_refused(site: Site) -> None:
    me, other = site.browser(), site.browser()
    preview = _preview(me, "sanal", "alis", {"fon": "XHT", "gun": "2026-11-25", "tutar": "1000"})
    fields = hidden_fields(preview.text, "/sanal/islemler/kaydet")

    assert other.post("/sanal/islemler/kaydet", fields).status_code == 403
    assert me.post("/gercek/islemler/kaydet", fields).status_code == 403
    assert site.rows("sanal") == []


def test_a_confirmation_older_than_ten_minutes_asks_for_a_new_preview(site: Site) -> None:
    me = site.browser()
    preview = _preview(me, "real", "alis", REAL_BUY)
    site.clock.advance(timedelta(minutes=10, seconds=1))
    assert me.unlock(PASSWORD).status_code == 303

    late = _confirm(me, "real", preview)

    assert late.status_code == 400
    assert "Önizleme 10 dakikadan eski" in late.text
    assert len(site.rows("real")) == len(scenario.TRADES)


@pytest.mark.parametrize("path", ["/gercek/islemler/yeni/alis", "/gercek/islemler/5/iptal"])
def test_a_locked_session_is_sent_to_the_lock_page_first(site: Site, path: str) -> None:
    me = site.browser(unlocked=False)

    response = me.get(path)

    assert response.status_code == 303
    assert response.headers["location"] == f"/gercek/kilit?sonra={path}"


def test_a_locked_session_cannot_save_even_with_a_signed_form(site: Site) -> None:
    me = site.browser()
    preview = _preview(me, "real", "alis", REAL_BUY)
    site.clock.advance(timedelta(minutes=15))

    response = _confirm(me, "real", preview)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/gercek/kilit?sonra=")
    assert len(site.rows("real")) == len(scenario.TRADES)


@pytest.mark.parametrize(
    "path",
    [
        "/gercek/islemler/yeni/alis",
        "/gercek/islemler/kaydet",
        "/gercek/islemler/1/iptal",
        "/sanal/islemler/yeni/satis",
    ],
)
def test_every_write_post_checks_origin_and_token(site: Site, path: str) -> None:
    me = site.browser()

    assert me.post(path, REAL_BUY, headers={}).status_code == 403
    assert me.post(path, REAL_BUY, token="0" * 64).status_code == 403


def test_without_a_password_hash_writing_is_not_set_up(tmp_path: Path, migrated_db: Path) -> None:
    site = _site(tmp_path, migrated_db, stored=None)
    me = site.browser(unlocked=False)

    listing = me.get("/gercek/islemler").text
    form = me.get("/gercek/islemler/yeni/alis")
    post = _preview(me, "real", "alis", REAL_BUY)

    assert "Yazma bu cihazda kurulmadı." in listing
    assert "/islemler/yeni/alis" not in listing
    assert "/iptal" not in listing
    assert form.status_code == 403
    assert "Yazma bu cihazda kurulmadı." in form.text
    assert post.status_code == 403


def test_a_void_shows_the_k58_list_first_then_previews_and_saves(site: Site) -> None:
    me = site.browser()
    sell = _preview(me, "real", "satis", {**REAL_BUY, "adet": "105", "dekont": ""})
    assert _confirm(me, "real", sell).status_code == 303

    blocked = me.get("/gercek/islemler/4/iptal")
    assert blocked.status_code == 409
    assert '<a href="/gercek/islemler/5/iptal">#5</a>' in blocked.text
    assert 'name="gerekce"' not in blocked.text

    form = me.get("/gercek/islemler/5/iptal")
    assert 'name="gerekce"' in form.text
    empty = me.post("/gercek/islemler/5/iptal", {"gerekce": "  "})
    assert empty.status_code == 400
    assert "Gerekçe boş bırakılamaz" in empty.text

    preview = me.post("/gercek/islemler/5/iptal", {"gerekce": "yanlış adet"})
    assert preview.status_code == 200
    assert GERCEK in preview.text
    assert "İptali kaydet" in preview.text
    assert site.rows("real")[-1].voided_at is None
    saved = _confirm(me, "real", preview)

    assert saved.headers["location"] == "/gercek/islemler?islem=iptal&no=5"
    assert "#5 numaralı işlem iptal edildi." in me.get(saved.headers["location"]).text
    assert site.rows("real")[-1].void_reason == "yanlış adet"
    assert me.get("/gercek/islemler/4/iptal").status_code == 200


def test_the_log_holds_only_number_kind_and_profile(
    site: Site, caplog: pytest.LogCaptureFixture
) -> None:
    me = site.browser()
    with caplog.at_level(logging.INFO, logger="finans.web"):
        _confirm(me, "real", _preview(me, "real", "alis", REAL_BUY))
        _confirm(me, "real", me.post("/gercek/islemler/5/iptal", {"gerekce": "yanlış gün"}))

    logged = [r.getMessage() for r in caplog.records if r.name == "finans.web"]
    assert logged == ["İşlem kaydedildi: #5 alis (real)", "İşlem iptal edildi: #5 (real)"]


def test_the_transactions_page_offers_writing_per_profile(site: Site) -> None:
    me = site.browser()

    real = me.get("/gercek/islemler").text
    sanal = me.get("/sanal/islemler").text

    assert 'href="/gercek/islemler/yeni/alis"' in real
    assert 'href="/gercek/islemler/1/iptal"' in real
    assert 'href="/sanal/islemler/yeni/alis"' in sanal
    assert "Sanal alım" in sanal


@pytest.mark.parametrize(
    "path",
    [
        "/gercek/islemler/yeni/alis",
        "/gercek/islemler/yeni/satis",
        "/sanal/islemler/yeni/alis",
        "/sanal/islemler/yeni/satis",
        "/gercek/islemler/1/iptal",
    ],
)
def test_write_pages_keep_the_page_rules(site: Site, path: str) -> None:
    """K-128: tek h1, satır içi stil ve betik yok, her alanın etiketi var."""
    page = site.browser().get(path).text

    assert page.count("<h1") == 1
    assert "style=" not in page
    assert "<script" not in page
    for field in re.findall(r'<(?:input|select|textarea) id="([^"]+)"', page):
        assert f'<label for="{field}">' in page
