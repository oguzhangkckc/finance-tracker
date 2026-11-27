"""Yazma uçları (K-105, K-137, K-138): önizleme yazmaz; kayıt onayı doğrular, sonucu yeniden
hesaplar; aynı onay bir kez yazılır; CLI ile aynı satır."""

import logging
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from finans.adapters.sqlite import connection as sqlite_connection
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.api.app import create_app
from finans.api.errors import BUSY
from finans.api.routes import islem
from finans.ports.repositories import StoredTransaction
from finans.settings import Profile, Settings, profile_settings
from finans.sunum.writes import FormErrors, ResultChanged
from tests.fakes.access import FakeAccessKeys
from tests.fakes.clock import FixedClock
from tests.support.access import API_SETTINGS, access_token
from tests.support.api_client import ACCESS_HEADER, ApiClient
from tests.support.profiles import two_profiles
from tests.support.writes import NOW, cli_rows, cli_twin, priced_sanal, run_cli, same_row

REAL_BUY = {
    "fund": "XHT",
    "day": "2026-11-25",
    "units": "10",
    "price": "11,000000",
    "fee": "0",
    "ref": "D-1",
}
SANAL_BUY = {"fund": "XHT", "day": "2026-11-25", "amount": "1000", "fee": "0"}
REFUSED = {"error": "İstek reddedildi.", "fields": {}}


@pytest.fixture
def clock() -> FixedClock:
    # İstanbul'da Çarşamba 12:30; senaryonun 25 Kasım fiyatları kayıtlı, XHT'de 110 pay var.
    return FixedClock(NOW)


@pytest.fixture
def site(tmp_path: Path, migrated_db: Path) -> Settings:
    settings = two_profiles(tmp_path, migrated_db)
    priced_sanal(profile_settings(settings)["sanal"])
    return settings


@pytest.fixture
def app(site: Settings, keys: FakeAccessKeys, clock: FixedClock) -> FastAPI:
    return create_app(site, API_SETTINGS, keys=keys, clock=clock)


@pytest.fixture
def me(app: FastAPI, clock: FixedClock) -> ApiClient:
    return ApiClient(app, clock)


def rows(site: Settings, profile: Profile) -> list[StoredTransaction]:
    conf = profile_settings(site)[profile]
    with SqliteUnitOfWork(conf.db_path, readonly=True, sanal=profile == "sanal") as uow:
        return uow.transactions.list(include_voided=True)


def confirm(me: ApiClient, path: str, preview: dict[str, object]) -> httpx.Response:
    return me.post(path, json={"confirmation": preview["confirmation"]})


def test_a_real_buy_is_previewed_without_writing_and_saved_as_the_cli_would(
    me: ApiClient, site: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY)

    assert preview.status_code == 200
    body = preview.json()
    assert {key: value for key, value in body.items() if key != "confirmation"} == {
        "profile": "gercek",
        "kind": "alis",
        "instrument": "XHT",
        "fund_name": "XHT",
        "trade_date": "2026-11-25",
        "side": "BUY",
        "units": "10",
        "unit_price": "11",
        "fee": "0",
        "gross": "110",
        "ref": "D-1",
        "units_before": "110",
        "units_after": "120",
        "leftover": None,
        "warnings": [],
        "changed": False,
    }
    assert len(rows(site, "real")) == 4

    saved = confirm(me, "/api/gercek/islemler/kaydet", body)

    assert (saved.status_code, saved.json()) == (200, {"number": 5, "duplicate": False})
    twin = cli_twin(tmp_path)
    args = ["tx", "add", "buy", "XHT", "10", "11.000000", "--date", "2026-11-25", "--ref", "D-1"]
    run_cli(twin, "real", args, monkeypatch)
    assert same_row(rows(site, "real")[-1]) == same_row(cli_rows(twin, "real")[-1])


def test_the_same_confirmation_twice_is_written_once(me: ApiClient, site: Settings) -> None:
    body = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    first = confirm(me, "/api/gercek/islemler/kaydet", body)
    again = confirm(me, "/api/gercek/islemler/kaydet", body)

    assert first.json() == {"number": 5, "duplicate": False}
    assert (again.status_code, again.json()) == (200, {"number": 5, "duplicate": True})
    assert len(rows(site, "real")) == 5


def test_a_result_that_changed_is_not_saved_and_comes_back_as_a_new_preview(
    me: ApiClient, site: Settings
) -> None:
    stale = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    other = me.post(
        "/api/gercek/islemler/alis/onizle", json={**REAL_BUY, "units": "5", "ref": "D-2"}
    ).json()
    assert confirm(me, "/api/gercek/islemler/kaydet", other).status_code == 200

    changed = confirm(me, "/api/gercek/islemler/kaydet", stale)

    assert changed.status_code == 409
    fresh = changed.json()
    assert (fresh["changed"], fresh["units_before"], fresh["units_after"]) == (True, "115", "125")
    assert len(rows(site, "real")) == 5
    assert confirm(me, "/api/gercek/islemler/kaydet", fresh).json() == {
        "number": 6,
        "duplicate": False,
    }


def test_an_expired_confirmation_saves_nothing(
    me: ApiClient, site: Settings, clock: FixedClock
) -> None:
    body = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    clock.advance(timedelta(minutes=11))

    saved = confirm(me, "/api/gercek/islemler/kaydet", body)

    assert saved.status_code == 422
    assert saved.json()["error"].startswith("Önizleme 10 dakikadan eski")
    assert len(rows(site, "real")) == 4


def test_a_tampered_confirmation_is_refused(
    me: ApiClient, site: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    body = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    tampered = {**body["confirmation"], "adet": "1000"}

    with caplog.at_level(logging.WARNING, logger="finans.api"):
        saved = me.post("/api/gercek/islemler/kaydet", json={"confirmation": tampered})

    assert (saved.status_code, saved.json()) == (403, REFUSED)
    assert [r.getMessage() for r in caplog.records] == ["Onay reddedildi (gercek): imza geçersiz"]
    assert len(rows(site, "real")) == 4


@pytest.mark.parametrize("confirmation", [{}, {"islem": "alis"}, {"islem": "sil", "imza": "x"}])
def test_a_confirmation_without_a_valid_signature_or_kind_is_refused(
    me: ApiClient, confirmation: dict[str, str]
) -> None:
    saved = me.post("/api/gercek/islemler/kaydet", json={"confirmation": confirmation})
    assert (saved.status_code, saved.json()) == (403, REFUSED)


def test_a_confirmation_from_the_other_profile_is_refused(me: ApiClient, site: Settings) -> None:
    body = me.post("/api/sanal/islemler/alis/onizle", json=SANAL_BUY).json()

    saved = confirm(me, "/api/gercek/islemler/kaydet", body)

    assert (saved.status_code, saved.json()) == (403, REFUSED)
    assert (len(rows(site, "real")), len(rows(site, "sanal"))) == (4, 0)


def test_a_confirmation_for_another_kind_of_write_is_refused(me: ApiClient) -> None:
    preview = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "yanlış"}).json()
    saved = confirm(me, "/api/gercek/islemler/kaydet", preview)
    assert (saved.status_code, saved.json()) == (403, REFUSED)


def test_the_confirmation_is_bound_to_the_access_email(
    site: Settings, keys: FakeAccessKeys, clock: FixedClock, me: ApiClient
) -> None:
    body = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    other_settings = replace(API_SETTINGS, allowed_email="baska@example.com")
    other = ApiClient(create_app(site, other_settings, keys=keys, clock=clock), clock, signed=False)
    token = access_token(clock.now(), email="baska@example.com")

    saved = other.post(
        "/api/gercek/islemler/kaydet",
        json={"confirmation": body["confirmation"]},
        headers={ACCESS_HEADER: token},
    )

    assert (saved.status_code, saved.json()) == (403, REFUSED)
    assert len(rows(site, "real")) == 4


def test_the_email_case_does_not_matter_for_the_confirmation(
    app: FastAPI, clock: FixedClock
) -> None:
    shouting = ApiClient(app, clock, signed=False)
    headers = {ACCESS_HEADER: access_token(clock.now(), email="KULLANICI@example.com")}
    body = shouting.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY, headers=headers).json()

    saved = confirm(ApiClient(app, clock), "/api/gercek/islemler/kaydet", body)

    assert saved.json() == {"number": 5, "duplicate": False}


@pytest.mark.parametrize(
    ("change", "fields"),
    [
        (
            {"price": "11.5"},
            {
                "price": "Birim fiyat: nokta kullanılmaz; ondalık ayırıcı virgüldür (1,5), "
                "binlik ayırıcı yazılmaz (5000)."
            },
        ),
        ({"fund": ""}, {"fund": "Fon seç."}),
        (
            {"day": "25.11.2026"},
            {"day": "Tarih YYYY-AA-GG biçiminde olmalı, '25.11.2026' verildi."},
        ),
        ({"units": "0"}, {"units": "Adet sıfırdan büyük olmalı."}),
    ],
)
def test_form_errors_name_the_json_fields(
    me: ApiClient, change: dict[str, str], fields: dict[str, str]
) -> None:
    response = me.post("/api/gercek/islemler/alis/onizle", json={**REAL_BUY, **change})
    assert (response.status_code, response.json()) == (
        422,
        {"error": "Girdi geçersiz.", "fields": fields},
    )


def test_a_trade_the_rules_refuse_is_a_422_with_the_reason(me: ApiClient) -> None:
    response = me.post(
        "/api/gercek/islemler/satis/onizle", json={**REAL_BUY, "units": "500", "ref": ""}
    )
    assert response.status_code == 422
    assert "XHT" in response.json()["error"]


def test_a_sanal_buy_by_amount_and_a_sale_of_everything_match_the_cli(
    me: ApiClient, site: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    buy = me.post("/api/sanal/islemler/alis/onizle", json=SANAL_BUY).json()
    assert (buy["units"], buy["unit_price"], buy["leftover"], buy["profile"]) == (
        "90",
        "11",
        "10",
        "sanal",
    )
    assert confirm(me, "/api/sanal/islemler/kaydet", buy).status_code == 200
    sell = me.post(
        "/api/sanal/islemler/satis/onizle",
        json={"fund": "XHT", "day": "2026-11-25", "all": True},
    ).json()
    assert (sell["units"], sell["units_after"]) == ("90", "0")
    assert confirm(me, "/api/sanal/islemler/kaydet", sell).status_code == 200

    twin = cli_twin(tmp_path)
    run_cli(
        twin,
        "sanal",
        ["sanal", "al", "XHT", "--tutar", "1000", "--tarih", "2026-11-25"],
        monkeypatch,
    )
    run_cli(twin, "sanal", ["sanal", "sat", "XHT", "90", "--tarih", "2026-11-25"], monkeypatch)
    api, cli = rows(site, "sanal"), cli_rows(twin, "sanal")
    assert [same_row(s) for s in api] == [same_row(s) for s in cli]


def test_a_sanal_trade_on_a_day_without_a_price_offers_the_nearest_days(me: ApiClient) -> None:
    response = me.post("/api/sanal/islemler/alis/onizle", json={**SANAL_BUY, "day": "2026-11-24"})

    assert response.status_code == 422
    body = response.json()
    assert body["price_days"] == ["2026-11-20", "2026-11-25"]
    assert body["fields"] == {"day": body["error"]}


def test_a_void_shows_its_target_then_saves_with_the_reason(me: ApiClient, site: Settings) -> None:
    target = me.get("/api/gercek/islemler/4/iptal")
    assert (target.status_code, target.json()) == (
        200,
        {
            "id": 4,
            "instrument": "XHT",
            "trade_date": "2026-11-25",
            "side": "BUY",
            "units": "10",
            "unit_price": "11",
            "fee": "0",
            "external_ref": None,
            "note": None,
        },
    )
    missing = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": " "})
    assert missing.json() == {
        "error": "Girdi geçersiz.",
        "fields": {"reason": "Gerekçe boş bırakılamaz; neden iptal edildiği kayıtta kalır."},
    }

    preview = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "yanlış adet"}).json()
    assert (preview["reason"], preview["target"]["id"], preview["changed"]) == (
        "yanlış adet",
        4,
        False,
    )
    saved = confirm(me, "/api/gercek/islemler/4/iptal/kaydet", preview)

    assert saved.json() == {"number": 4, "duplicate": False}
    assert rows(site, "real")[-1].void_reason == "yanlış adet"
    gone = me.get("/api/gercek/islemler/4/iptal")
    assert gone.status_code == 404
    assert gone.json()["error"]


def test_a_void_confirmation_for_another_transaction_is_refused(
    me: ApiClient, site: Settings
) -> None:
    preview = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "yanlış"}).json()
    saved = confirm(me, "/api/gercek/islemler/3/iptal/kaydet", preview)
    assert (saved.status_code, saved.json()) == (403, REFUSED)
    assert all(row.voided_at is None for row in rows(site, "real"))


def test_a_void_that_later_sales_need_is_blocked_with_the_sales(me: ApiClient) -> None:
    sell = me.post(
        "/api/gercek/islemler/satis/onizle",
        json={**REAL_BUY, "units": "110", "ref": "S-1"},
    ).json()
    assert confirm(me, "/api/gercek/islemler/kaydet", sell).status_code == 200

    preview = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "yanlış"})
    info = me.get("/api/gercek/islemler/4/iptal")

    assert preview.status_code == 422
    assert preview.json()["blocking"] == [
        {"id": 5, "instrument": "XHT", "trade_date": "2026-11-25", "units": "110"}
    ]
    assert (info.status_code, info.json()["blocking"]) == (422, preview.json()["blocking"])


def test_a_void_whose_result_changed_comes_back_as_a_new_preview(
    me: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "yanlış"}).json()

    def changed(*_args: object, **_kwargs: object) -> None:
        raise ResultChanged

    monkeypatch.setattr(islem, "record_void", changed)
    response = confirm(me, "/api/gercek/islemler/4/iptal/kaydet", preview)

    assert response.status_code == 409
    assert (response.json()["changed"], response.json()["target"]["id"]) == (True, 4)


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/maas-gunu"), ("POST", "/maas-gunu/onizle"), ("POST", "/maas-gunu/kaydet")],
)
def test_the_payday_plan_has_no_address_in_the_real_profile(
    me: ApiClient, method: str, path: str
) -> None:
    body: dict[str, object] = {"confirmation": {}} if path.endswith("kaydet") else {}
    response = me.request(method, f"/api/gercek{path}", json=None if method == "GET" else body)
    assert (response.status_code, response.json()) == (404, {"error": "Bulunamadı.", "fields": {}})


def test_the_sanal_payday_plan_is_applied_once(me: ApiClient, site: Settings) -> None:
    plan = me.get("/api/sanal/maas-gunu").json()

    assert (plan["payday"], plan["ready"], plan["changed"]) == ("2026-11-15", 2, False)
    assert [(line["instrument"], line["status"]) for line in plan["lines"]] == [
        ("XPP", "ready"),
        ("XHT", "ready"),
    ]
    assert plan["lines"][0]["class_name"] == "Düşük risk"
    saved = confirm(me, "/api/sanal/maas-gunu/kaydet", plan)
    again = confirm(me, "/api/sanal/maas-gunu/kaydet", plan)

    assert saved.json() == {"number": 2, "duplicate": False}
    assert again.json() == {"number": 2, "duplicate": True}
    assert len(rows(site, "sanal")) == 2
    after = me.get("/api/sanal/maas-gunu").json()
    assert (after["ready"], after["confirmation"]) == (0, None)


def test_a_payday_preview_reads_the_day_and_reports_bad_input(me: ApiClient) -> None:
    bad = me.post("/api/sanal/maas-gunu/onizle", json={"payday": "15 Kasım"})
    assert bad.json()["fields"] == {
        "payday": "Tarih YYYY-AA-GG biçiminde olmalı, '15 Kasım' verildi."
    }

    plan = me.post("/api/sanal/maas-gunu/onizle", json={"payday": "2026-11-15"}).json()
    assert (plan["payday"], plan["reapply_voided"], plan["ready"]) == ("2026-11-15", False, 2)


def test_a_payday_whose_plan_changed_comes_back_as_a_new_preview(
    me: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = me.get("/api/sanal/maas-gunu").json()

    def changed(*_args: object, **_kwargs: object) -> None:
        raise ResultChanged

    monkeypatch.setattr(islem, "record_payday", changed)
    response = confirm(me, "/api/sanal/maas-gunu/kaydet", plan)

    assert (response.status_code, response.json()["changed"]) == (409, True)


def test_a_price_refresh_is_requested_at_most_once_an_hour(me: ApiClient, site: Settings) -> None:
    first = me.post("/api/gercek/fiyat-guncelle", json={})
    second = me.post("/api/gercek/fiyat-guncelle", json={})

    assert (first.status_code, first.json()["accepted"]) == (200, True)
    assert (site.db_path.parent / "refresh" / "real.request").is_file()
    assert second.json()["accepted"] is False
    assert second.json()["refresh"]["reason"]


def test_a_refresh_request_that_cannot_be_written_is_a_503(me: ApiClient, site: Settings) -> None:
    (site.db_path.parent / "refresh").write_text("dizin değil", encoding="utf-8")

    response = me.post("/api/gercek/fiyat-guncelle", json={})

    assert (response.status_code, response.json()) == (
        503,
        {"error": "Güncelleme isteği yazılamadı; Sistem sayfasına bakın.", "fields": {}},
    )


def test_saving_logs_only_number_kind_and_profile(
    me: ApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    body = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    with caplog.at_level(logging.INFO, logger="finans"):
        confirm(me, "/api/gercek/islemler/kaydet", body)

    logged = [r.getMessage() for r in caplog.records if r.name.startswith("finans")]
    assert logged == ["İşlem kaydedildi: #5 alis (real)"]


def test_a_sale_that_another_sale_overtook_is_refused_with_the_reason(
    me: ApiClient, site: Settings
) -> None:
    everything = me.post(
        "/api/gercek/islemler/satis/onizle", json={**REAL_BUY, "units": "110", "ref": "S-1"}
    ).json()
    part = me.post(
        "/api/gercek/islemler/satis/onizle", json={**REAL_BUY, "units": "10", "ref": "S-2"}
    ).json()
    assert confirm(me, "/api/gercek/islemler/kaydet", part).status_code == 200

    late = confirm(me, "/api/gercek/islemler/kaydet", everything)

    assert late.status_code == 422
    assert "XHT" in late.json()["error"]
    assert len(rows(site, "real")) == 5


def test_a_void_that_a_new_sale_blocks_is_not_saved(me: ApiClient, site: Settings) -> None:
    void = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "yanlış"}).json()
    sell = me.post(
        "/api/gercek/islemler/satis/onizle", json={**REAL_BUY, "units": "110", "ref": "S-1"}
    ).json()
    assert confirm(me, "/api/gercek/islemler/kaydet", sell).status_code == 200

    blocked = confirm(me, "/api/gercek/islemler/4/iptal/kaydet", void)

    assert blocked.status_code == 422
    assert [sale["id"] for sale in blocked.json()["blocking"]] == [5]
    assert all(row.voided_at is None for row in rows(site, "real"))


def test_a_second_void_of_the_same_transaction_is_refused_with_the_reason(me: ApiClient) -> None:
    first = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "bir"}).json()
    second = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "iki"}).json()
    assert confirm(me, "/api/gercek/islemler/4/iptal/kaydet", first).status_code == 200

    again = confirm(me, "/api/gercek/islemler/4/iptal/kaydet", second)

    assert again.status_code == 422
    assert again.json()["error"]


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("trade", "/api/gercek/islemler/4/iptal/kaydet"),
        ("payday", "/api/sanal/islemler/kaydet"),
        ("trade-sanal", "/api/sanal/maas-gunu/kaydet"),
    ],
)
def test_a_confirmation_sent_to_another_kind_of_write_is_refused(
    me: ApiClient, source: str, target: str
) -> None:
    if source == "trade":
        preview = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    elif source == "payday":
        preview = me.get("/api/sanal/maas-gunu").json()
    else:
        preview = me.post("/api/sanal/islemler/alis/onizle", json=SANAL_BUY).json()

    response = confirm(me, target, preview)
    assert (response.status_code, response.json()) == (403, REFUSED)


def test_a_payday_confirmation_that_was_altered_is_refused(me: ApiClient, site: Settings) -> None:
    plan = me.get("/api/sanal/maas-gunu").json()
    altered = {**plan["confirmation"], "maas_gunu": "2026-10-15"}

    saved = me.post("/api/sanal/maas-gunu/kaydet", json={"confirmation": altered})

    assert (saved.status_code, saved.json()) == (403, REFUSED)
    assert rows(site, "sanal") == []


def _rules_changed(*_args: object, **_kwargs: object) -> None:
    raise FormErrors({"adet": "Adet artık kabul edilmiyor."})


def test_signed_input_that_the_rules_no_longer_accept_is_not_saved(
    me: ApiClient, site: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    trade = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()
    void = me.post("/api/gercek/islemler/4/iptal/onizle", json={"reason": "yanlış"}).json()
    plan = me.get("/api/sanal/maas-gunu").json()
    for name in ("read_trade", "read_reason", "read_payday"):
        monkeypatch.setattr(islem, name, _rules_changed)

    trade_saved = confirm(me, "/api/gercek/islemler/kaydet", trade)
    void_saved = confirm(me, "/api/gercek/islemler/4/iptal/kaydet", void)
    payday_saved = confirm(me, "/api/sanal/maas-gunu/kaydet", plan)

    assert (trade_saved.status_code, trade_saved.json()) == (
        422,
        {"error": "Girdi geçersiz.", "fields": {"units": "Adet artık kabul edilmiyor."}},
    )
    assert (void_saved.status_code, payday_saved.status_code) == (403, 403)
    assert (len(rows(site, "real")), rows(site, "sanal")) == (4, [])


def test_a_save_while_a_job_holds_the_database_saves_nothing_and_can_be_retried(
    me: ApiClient, site: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite_connection, "BUSY_TIMEOUT_MS", 50)
    body = me.post("/api/gercek/islemler/alis/onizle", json=REAL_BUY).json()

    with closing(connect(site.db_path)) as job:
        job.execute("BEGIN IMMEDIATE")
        busy = confirm(me, "/api/gercek/islemler/kaydet", body)
        job.execute("ROLLBACK")

    assert (busy.status_code, busy.json(), busy.headers["retry-after"]) == (
        503,
        {"error": BUSY, "fields": {}},
        "5",
    )
    assert len(rows(site, "real")) == 4
    retried = confirm(me, "/api/gercek/islemler/kaydet", body)
    assert retried.json() == {"number": 5, "duplicate": False}
