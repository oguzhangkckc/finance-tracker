"""Ayar yazmaları (K-127, K-137): yürürlük tarihli sürüm, sanala da uygulama, sonraki sürümlere
taşıma ve vazgeçme; önizleme yazmaz, onay imzalı ve tek kullanımlık."""

from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from finans import bootstrap
from finans.adapters.sqlite import connection as sqlite_connection
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.api.app import create_app
from finans.api.errors import BUSY
from finans.api.routes import ayar
from finans.application.settings import effective_config
from finans.domain.models import DomainError
from finans.domain.settings import SettingVersion
from finans.ports.repositories import StoredSetting
from finans.settings import Profile, Settings, profile_settings
from finans.sunum import setting_writes
from finans.sunum.setting_writes import SettingRequest
from finans.sunum.views import PageError
from finans.sunum.writes import FormErrors, ResultChanged
from tests.fakes.access import FakeAccessKeys
from tests.fakes.clock import FixedClock
from tests.support.access import API_SETTINGS
from tests.support.api_client import ApiClient
from tests.support.profiles import two_profiles
from tests.support.writes import NOW, priced_sanal, start_settings

D = Decimal
REAL = "/api/gercek/ayarlar"
SANAL = "/api/sanal/ayarlar"
RAISE = {"day": "2026-12-01", "contribution": "1200"}
REFUSED = {"error": "İstek reddedildi.", "fields": {}}
START = SettingVersion(date.min, 15, D(1000), {"hisse": D("0.6"), "dusuk_risk": D("0.4")})
JANUARY = replace(START, effective_from=date(2027, 1, 1), monthly_contribution=D(1200))
MARCH = replace(
    START, effective_from=date(2027, 3, 1), targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")}
)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def site(tmp_path: Path, migrated_db: Path) -> Settings:
    settings = two_profiles(tmp_path, migrated_db)
    priced_sanal(profile_settings(settings)["sanal"])
    start_settings(settings)
    return settings


@pytest.fixture
def app(site: Settings, keys: FakeAccessKeys, clock: FixedClock) -> FastAPI:
    return create_app(site, API_SETTINGS, keys=keys, clock=clock)


@pytest.fixture
def me(app: FastAPI, clock: FixedClock) -> ApiClient:
    return ApiClient(app, clock)


def conf(site: Settings, profile: Profile) -> Settings:
    return profile_settings(site)[profile]


def versions(site: Settings, profile: Profile) -> list[StoredSetting]:
    settings = conf(site, profile)
    with SqliteUnitOfWork(settings.db_path, readonly=True, sanal=profile == "sanal") as uow:
        return uow.settings.list()


def add(site: Settings, profile: Profile, version: SettingVersion) -> None:
    settings = conf(site, profile)
    with SqliteUnitOfWork(settings.db_path, sanal=profile == "sanal") as uow:
        uow.settings.add(version, source="web", at=NOW)


def contribution_on(site: Settings, on: date) -> Decimal | None:
    settings = conf(site, "real")
    assert settings.portfolio_path is not None
    config = bootstrap.portfolio_source().load(settings.portfolio_path)
    with SqliteUnitOfWork(settings.db_path, readonly=True) as uow:
        return effective_config(uow, config, on=on).monthly_contribution


def save(me: ApiClient, path: str, preview: dict[str, object]) -> httpx.Response:
    return me.post(path, json={"confirmation": preview["confirmation"]})


def test_a_new_contribution_is_previewed_then_saved_as_a_version(
    me: ApiClient, site: Settings
) -> None:
    preview = me.post(f"{REAL}/onizle", json=RAISE)

    assert preview.status_code == 200
    body = preview.json()
    [plan] = body["plans"]
    assert plan == {
        "profile": "gercek",
        "problem": None,
        "version": {
            "effective_from": "2026-12-01",
            "initial": False,
            "values": {
                "payday": 15,
                "monthly_contribution": "1200",
                "targets": {"dusuk_risk": "0.4", "hisse": "0.6"},
            },
        },
        "base": {
            "effective_from": "0001-01-01",
            "initial": True,
            "values": {
                "payday": 15,
                "monthly_contribution": "1000",
                "targets": {"dusuk_risk": "0.4", "hisse": "0.6"},
            },
        },
        "changed_fields": ["monthly_contribution"],
        "changes": [{"setting": "Aylık katkı", "change": "1.000,00 TL → 1.200,00 TL"}],
        "issues": [],
        "later": [],
        "ready": True,
    }
    assert (body["carry_option"], body["carry"], body["changed"]) == (False, False, False)
    assert len(versions(site, "real")) == 1

    saved = save(me, f"{REAL}/kaydet", body)

    assert (saved.status_code, saved.json()) == (
        200,
        {
            "outcomes": [
                {
                    "profile": "gercek",
                    "status": "saved",
                    "setting_id": 2,
                    "rewritten": [],
                    "message": "",
                }
            ]
        },
    )
    assert versions(site, "real")[-1].version.monthly_contribution == D(1200)
    assert len(versions(site, "sanal")) == 1


def test_the_same_confirmation_twice_writes_one_version(me: ApiClient, site: Settings) -> None:
    body = me.post(f"{REAL}/onizle", json=RAISE).json()
    save(me, f"{REAL}/kaydet", body)

    again = save(me, f"{REAL}/kaydet", body)

    assert [(o["status"], o["setting_id"]) for o in again.json()["outcomes"]] == [("duplicate", 2)]
    assert len(versions(site, "real")) == 2


def test_a_value_equal_to_todays_is_not_a_change(me: ApiClient) -> None:
    body = me.post(
        f"{REAL}/onizle", json={"day": "2026-12-01", "contribution": "1000", "payday": "15"}
    ).json()

    [plan] = body["plans"]
    assert (plan["changed_fields"], plan["ready"], body["confirmation"]) == ([], False, None)
    assert plan["issues"] == ["ayar: o günkü ayarla aynı; yeni sürüm gerekmiyor."]


@pytest.mark.parametrize(
    ("given", "fields"),
    [
        (
            {"day": "", "contribution": "1.200"},
            {
                "day": "Tarih YYYY-AA-GG biçiminde olmalı, '' verildi.",
                "contribution": "Aylık katkı: nokta kullanılmaz; ondalık ayırıcı virgüldür (1,5), "
                "binlik ayırıcı yazılmaz (5000).",
            },
        ),
        (
            {"targets": {"hisse": "50", "dusuk_risk": "40"}},
            {"targets": "Hedeflerin toplamı %90; %10 eksik. Toplam tam %100 olmalı."},
        ),
        (
            {"targets": {"hisse": "60"}},
            {"targets.dusuk_risk": "Düşük risk boş bırakılamaz; hedef yoksa 0 yaz."},
        ),
        ({"targets": {"hisse": "60", "yok": "40"}}, {"targets.yok": "Portföyde bu sınıf yok."}),
        ({"payday": ""}, {"payday": "Maaş günü boş bırakılamaz."}),
        ({"payday": "32"}, {"payday": "Maaş günü 1 ile 31 arasında bir gün olmalı."}),
    ],
)
def test_form_errors_name_the_json_fields(
    me: ApiClient, given: dict[str, object], fields: dict[str, str]
) -> None:
    response = me.post(f"{REAL}/onizle", json={"day": "2026-12-01", **given})
    assert (response.status_code, response.json()) == (
        422,
        {"error": "Girdi geçersiz.", "fields": fields},
    )


def test_targets_are_percent_and_saved_as_ratios(me: ApiClient, site: Settings) -> None:
    targets = {"hisse": "62,5", "dusuk_risk": "37,5"}
    body = me.post(f"{REAL}/onizle", json={"day": "2026-12-01", "targets": targets}).json()
    assert body["plans"][0]["changes"] == [
        {"setting": "Hedefler", "change": "Hisse %60 → %62,5, Düşük risk %40 → %37,5"}
    ]

    save(me, f"{REAL}/kaydet", body)

    assert versions(site, "real")[-1].version.targets == {
        "hisse": D("0.625"),
        "dusuk_risk": D("0.375"),
    }


def test_without_a_starting_version_the_preview_says_how_to_start(
    tmp_path: Path, migrated_db: Path, keys: FakeAccessKeys, clock: FixedClock
) -> None:
    site = two_profiles(tmp_path, migrated_db)
    me = ApiClient(create_app(site, API_SETTINGS, keys=keys, clock=clock), clock)

    response = me.post(f"{REAL}/onizle", json=RAISE)

    assert (response.status_code, response.json()) == (
        422,
        {
            "error": "Ayarların başlangıç sürümü yok; önce `ft config apply` çalıştır.",
            "fields": {},
        },
    )


def test_the_real_profile_can_write_the_same_change_to_sanal(me: ApiClient, site: Settings) -> None:
    body = me.post(f"{REAL}/onizle", json={**RAISE, "also_sanal": True}).json()
    assert [plan["profile"] for plan in body["plans"]] == ["gercek", "sanal"]

    saved = save(me, f"{REAL}/kaydet", body).json()

    assert [(o["profile"], o["status"]) for o in saved["outcomes"]] == [
        ("gercek", "saved"),
        ("sanal", "saved"),
    ]
    assert [len(versions(site, p)) for p in ("real", "sanal")] == [2, 2]


def test_the_sanal_profile_has_no_also_sanal(me: ApiClient, site: Settings) -> None:
    body = me.post(f"{SANAL}/onizle", json={**RAISE, "also_sanal": True}).json()
    assert [plan["profile"] for plan in body["plans"]] == ["sanal"]

    save(me, f"{SANAL}/kaydet", body)

    assert [len(versions(site, p)) for p in ("real", "sanal")] == [1, 2]


def test_a_busy_sanal_database_is_retried_with_the_same_confirmation(
    me: ApiClient, site: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite_connection, "BUSY_TIMEOUT_MS", 50)
    body = me.post(f"{REAL}/onizle", json={**RAISE, "also_sanal": True}).json()

    with closing(connect(conf(site, "sanal").db_path, sanal=True)) as job:
        job.execute("BEGIN IMMEDIATE")
        busy = save(me, f"{REAL}/kaydet", body).json()
        job.execute("ROLLBACK")
    retried = save(me, f"{REAL}/kaydet", body).json()

    assert [(o["profile"], o["status"]) for o in busy["outcomes"]] == [
        ("gercek", "saved"),
        ("sanal", "busy"),
    ]
    assert [(o["profile"], o["status"], o["setting_id"]) for o in retried["outcomes"]] == [
        ("gercek", "duplicate", 2),
        ("sanal", "saved", 2),
    ]
    assert [len(versions(site, p)) for p in ("real", "sanal")] == [2, 2]


def test_a_busy_real_database_saves_nothing_and_can_be_retried(
    me: ApiClient, site: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite_connection, "BUSY_TIMEOUT_MS", 50)
    body = me.post(f"{REAL}/onizle", json=RAISE).json()

    with closing(connect(conf(site, "real").db_path)) as job:
        job.execute("BEGIN IMMEDIATE")
        busy = save(me, f"{REAL}/kaydet", body)
        job.execute("ROLLBACK")

    assert (busy.status_code, busy.json(), busy.headers["retry-after"]) == (
        503,
        {"error": BUSY, "fields": {}},
        "5",
    )
    assert len(versions(site, "real")) == 1
    assert save(me, f"{REAL}/kaydet", body).json()["outcomes"][0]["status"] == "saved"


def test_a_sanal_whose_result_changed_does_not_undo_the_real_one(
    me: ApiClient, site: Settings
) -> None:
    body = me.post(f"{REAL}/onizle", json={**RAISE, "also_sanal": True}).json()
    # Sanalda sonradan planlanan Mart sürümü katkıyı taşımaz; sanalın önerisi değişir.
    add(site, "sanal", MARCH)

    saved = save(me, f"{REAL}/kaydet", body).json()

    assert [(o["profile"], o["status"]) for o in saved["outcomes"]] == [
        ("gercek", "saved"),
        ("sanal", "changed"),
    ]
    assert [len(versions(site, p)) for p in ("real", "sanal")] == [2, 2]


def test_a_sanal_that_fails_does_not_undo_the_real_one(
    me: ApiClient, site: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = me.post(f"{REAL}/onizle", json={**RAISE, "also_sanal": True}).json()
    original = setting_writes.record_settings

    def sanal_fails(settings: Settings, *args: object, **kwargs: object) -> object:
        if settings.profile == "sanal":
            raise PageError("sanal veritabanı açılamadı")
        return original(settings, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ayar, "record_settings", sanal_fails)
    saved = save(me, f"{REAL}/kaydet", body).json()

    assert saved["outcomes"][1] == {
        "profile": "sanal",
        "status": "failed",
        "setting_id": None,
        "rewritten": [],
        "message": "sanal veritabanı açılamadı",
    }
    assert [len(versions(site, p)) for p in ("real", "sanal")] == [2, 1]


@pytest.mark.parametrize(("carry", "in_march"), [(False, D(1000)), (True, D(1200))])
def test_a_january_contribution_lasts_past_a_planned_march_change_only_when_carried(
    me: ApiClient, site: Settings, carry: bool, in_march: Decimal
) -> None:
    add(site, "real", MARCH)

    body = me.post(
        f"{REAL}/onizle", json={"day": "2027-01-01", "contribution": "1200", "carry": carry}
    ).json()
    saved = save(me, f"{REAL}/kaydet", body).json()

    assert (body["carry_option"], body["carry"]) == (True, carry)
    assert body["plans"][0]["later"] == [
        {
            "id": 2,
            "effective_from": "2027-03-01",
            "fields": ["monthly_contribution"],
            "kept": "aylık katkı 1.000,00 TL",
            "carried": [{"setting": "Aylık katkı", "change": "1.000,00 TL → 1.200,00 TL"}],
        }
    ]
    expected = [{"cancelled": 2, "written": 4}] if carry else []
    assert saved["outcomes"][0]["rewritten"] == expected
    assert contribution_on(site, date(2027, 3, 15)) == in_march


def test_carry_is_ignored_when_no_later_version_needs_it(me: ApiClient) -> None:
    body = me.post(f"{REAL}/onizle", json={**RAISE, "carry": True}).json()
    assert (body["carry_option"], body["carry"]) == (False, False)


def test_a_result_that_changed_is_not_saved_and_comes_back_as_a_new_preview(
    me: ApiClient, site: Settings
) -> None:
    stale = me.post(f"{REAL}/onizle", json={"day": "2027-01-01", "contribution": "1200"}).json()
    add(site, "real", MARCH)

    changed = save(me, f"{REAL}/kaydet", stale)

    assert changed.status_code == 409
    fresh = changed.json()
    assert (fresh["changed"], fresh["carry_option"]) == (True, True)
    assert len(versions(site, "real")) == 2
    assert save(me, f"{REAL}/kaydet", fresh).json()["outcomes"][0]["status"] == "saved"


def test_a_tampered_or_misplaced_setting_confirmation_is_refused(
    me: ApiClient, site: Settings
) -> None:
    body = me.post(f"{REAL}/onizle", json=RAISE).json()
    tampered = {**body["confirmation"], "katki": "9000"}

    assert me.post(f"{REAL}/kaydet", json={"confirmation": tampered}).json() == REFUSED
    assert save(me, f"{SANAL}/kaydet", body).json() == REFUSED
    assert save(me, f"{REAL}/2/vazgec/kaydet", body).json() == REFUSED
    assert len(versions(site, "real")) == 1


def test_signed_settings_that_no_longer_read_or_fit_are_refused(
    me: ApiClient, site: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = me.post(f"{REAL}/onizle", json=RAISE).json()
    sanal = me.post(f"{SANAL}/onizle", json=RAISE).json()
    original = setting_writes.read_request_fields

    def unreadable(*_args: object, **_kwargs: object) -> SettingRequest:
        raise FormErrors({"degisen": "İmzalı alanlar eksik."})

    def also_sanal(*args: object, **kwargs: object) -> SettingRequest:
        return replace(original(*args, **kwargs), also_sanal=True)  # type: ignore[arg-type]

    monkeypatch.setattr(ayar, "read_request_fields", unreadable)
    assert save(me, f"{REAL}/kaydet", real).json() == REFUSED
    monkeypatch.setattr(ayar, "read_request_fields", also_sanal)
    assert save(me, f"{SANAL}/kaydet", sanal).json() == REFUSED
    assert [len(versions(site, p)) for p in ("real", "sanal")] == [1, 1]


def test_a_save_the_rules_refuse_is_a_422(me: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = me.post(f"{REAL}/onizle", json=RAISE).json()

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise DomainError("Bu sürüm artık kaydedilemez.")

    monkeypatch.setattr(ayar, "record_settings", refuse)
    response = save(me, f"{REAL}/kaydet", body)

    assert (response.status_code, response.json()) == (
        422,
        {"error": "Bu sürüm artık kaydedilemez.", "fields": {}},
    )


def test_a_planned_version_is_cancelled_with_a_reason(me: ApiClient, site: Settings) -> None:
    add(site, "real", JANUARY)

    target = me.get(f"{REAL}/2/vazgec").json()
    missing = me.post(f"{REAL}/2/vazgec/onizle", json={"reason": ""})
    preview = me.post(f"{REAL}/2/vazgec/onizle", json={"reason": "katkı artmayacak"}).json()
    saved = save(me, f"{REAL}/2/vazgec/kaydet", preview)
    again = save(me, f"{REAL}/2/vazgec/kaydet", preview)

    assert (target["id"], target["state"], target["effective_from"]) == (2, "planned", "2027-01-01")
    assert missing.json()["fields"] == {
        "reason": "Gerekçe boş bırakılamaz; neden vazgeçildiği kayıtta kalır."
    }
    assert (preview["target"]["id"], preview["reason"], preview["changed"]) == (
        2,
        "katkı artmayacak",
        False,
    )
    assert (saved.json(), again.json()) == (
        {"number": 2, "duplicate": False},
        {"number": 2, "duplicate": True},
    )
    assert versions(site, "real")[1].cancel_reason == "katkı artmayacak"


def test_a_version_in_force_cannot_be_cancelled(me: ApiClient) -> None:
    for response in (
        me.get(f"{REAL}/1/vazgec"),
        me.post(f"{REAL}/1/vazgec/onizle", json={"reason": "yanlış"}),
    ):
        assert (response.status_code, response.json()) == (
            422,
            {
                "error": "1 numaralı ayar sürümü yürürlüğe girmiş; vazgeçilemez. Değiştirmek "
                "için yeni bir sürüm ekle.",
                "fields": {},
            },
        )


def test_cancelling_twice_and_cancelling_another_number_are_refused(
    me: ApiClient, site: Settings
) -> None:
    add(site, "real", JANUARY)
    add(site, "real", MARCH)
    first = me.post(f"{REAL}/2/vazgec/onizle", json={"reason": "bir"}).json()
    second = me.post(f"{REAL}/2/vazgec/onizle", json={"reason": "iki"}).json()

    assert save(me, f"{REAL}/3/vazgec/kaydet", first).json() == REFUSED
    assert save(me, f"{REAL}/2/vazgec/kaydet", first).status_code == 200
    late = save(me, f"{REAL}/2/vazgec/kaydet", second)

    assert late.status_code == 422
    assert late.json()["error"]
    assert versions(site, "real")[2].cancelled_at is None


def test_a_cancel_whose_result_changed_or_whose_reason_no_longer_reads(
    me: ApiClient, site: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    add(site, "real", JANUARY)
    preview = me.post(f"{REAL}/2/vazgec/onizle", json={"reason": "yanlış"}).json()

    def changed(*_args: object, **_kwargs: object) -> None:
        raise ResultChanged

    monkeypatch.setattr(ayar, "record_cancel", changed)
    response = save(me, f"{REAL}/2/vazgec/kaydet", preview)
    assert (response.status_code, response.json()["changed"]) == (409, True)

    def unreadable(*_args: object, **_kwargs: object) -> str:
        raise FormErrors({"gerekce": "Gerekçe en fazla 200 karakter olabilir."})

    monkeypatch.setattr(ayar, "read_cancel_reason", unreadable)
    assert save(me, f"{REAL}/2/vazgec/kaydet", preview).json() == REFUSED
    assert versions(site, "real")[1].cancelled_at is None


def test_a_sanal_plan_that_cannot_be_made_holds_back_the_confirmation(
    tmp_path: Path, migrated_db: Path, keys: FakeAccessKeys, clock: FixedClock
) -> None:
    site = two_profiles(tmp_path, migrated_db)
    add(site, "real", START)
    me = ApiClient(create_app(site, API_SETTINGS, keys=keys, clock=clock), clock)

    body = me.post(f"{REAL}/onizle", json={**RAISE, "also_sanal": True}).json()

    assert body["plans"][1] == {
        "profile": "sanal",
        "problem": "Ayarların başlangıç sürümü yok; önce `ft config apply` çalıştır.",
        "version": None,
        "base": None,
        "changed_fields": [],
        "changes": [],
        "issues": [],
        "later": [],
        "ready": False,
    }
    assert (body["plans"][0]["ready"], body["confirmation"]) == (True, None)
