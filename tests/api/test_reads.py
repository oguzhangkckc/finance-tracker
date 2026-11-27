"""Okuma uçları (K-138): web'deki sayfaların verisi, aynı `Report` nesnesinden; iki profil ayrı
(K-125); tablo kuralları K-129'daki gibi."""

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.api.app import create_app
from finans.api.encoding import CanonicalJSONResponse
from finans.api.pages import RunItem
from finans.domain.settings import SettingVersion
from finans.ports.repositories import AlertEvent, AlertState
from finans.settings import Settings, profile_settings
from finans.sunum.views import load_report, payday_text, report_text
from tests.fakes.access import FakeAccessKeys
from tests.support.access import API_SETTINGS
from tests.support.api_client import ApiClient
from tests.support.profiles import NOW, two_profiles
from tests.support.writes import start_settings

PAGES = (
    "ozet",
    "dagilim",
    "getiri",
    "raporlar/haftalik",
    "raporlar/aylik",
    "raporlar/maas-gunu",
    "varliklar",
    "varliklar/lotlar",
    "islemler",
    "alarmlar",
    "sistem",
    "ayarlar",
    "secenekler",
)
NOT_FOUND = {"error": "Bulunamadı.", "fields": {}}
CLASS_NAMES = {"acil_durum": "Acil durum", "dusuk_risk": "Düşük risk", "hisse": "Hisse"}
EXPONENT = re.compile(r"^-?[0-9.]+[eE][+-]?[0-9]+$")


@pytest.fixture
def site(tmp_path: Path, migrated_db: Path) -> Settings:
    return two_profiles(tmp_path, migrated_db)


def reader_for(settings: Settings, keys: FakeAccessKeys) -> ApiClient:
    app: FastAPI = create_app(settings, API_SETTINGS, keys=keys, clock=NOW)
    return ApiClient(app, NOW)


@pytest.fixture
def reader(site: Settings, keys: FakeAccessKeys) -> ApiClient:
    return reader_for(site, keys)


def leaves(node: object) -> list[object]:
    if isinstance(node, dict):
        return [leaf for value in node.values() for leaf in leaves(value)]
    if isinstance(node, list):
        return [leaf for item in node for leaf in leaves(item)]
    return [node]


def row_ids(reader: ApiClient, query: str) -> list[int]:
    return [row["id"] for row in reader.get(f"/api/gercek/islemler{query}").json()["table"]["rows"]]


@pytest.mark.parametrize("slug", ["gercek", "sanal"])
@pytest.mark.parametrize("page", PAGES)
def test_every_page_answers_with_money_as_text(reader: ApiClient, slug: str, page: str) -> None:
    response = reader.get(f"/api/{slug}/{page}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    values = leaves(response.json())
    assert not [value for value in values if isinstance(value, float)]
    assert not [value for value in values if isinstance(value, str) and EXPONENT.match(value)]


@pytest.mark.parametrize(
    "path", ["/api/demo/ozet", "/api/gercek/yok", "/api/gercek/raporlar/yillik", "/api/ozet"]
)
def test_an_unknown_profile_or_page_is_not_found(reader: ApiClient, path: str) -> None:
    response = reader.get(path)
    assert (response.status_code, response.json()) == (404, NOT_FOUND)


def test_the_profiles_are_kept_apart(reader: ApiClient) -> None:
    real = reader.get("/api/gercek/islemler").json()["table"]
    sanal = reader.get("/api/sanal/islemler").json()["table"]

    assert (real["total"], sanal["total"]) == (4, 0)
    assert {row["instrument"] for row in real["rows"]} == {"XHT", "XPP", "XAC"}
    assert reader.get("/api/sanal/varliklar").json()["table"]["rows"] == []


def test_report_pages_carry_the_report_that_telegram_gets(
    reader: ApiClient, site: Settings
) -> None:
    real = profile_settings(site)["real"]
    weekly = json.loads(bytes(CanonicalJSONResponse(load_report(real, NOW, kind="weekly")).body))
    monthly = json.loads(bytes(CanonicalJSONResponse(load_report(real, NOW, kind="monthly")).body))

    assert reader.get("/api/gercek/ozet").json()["report"] == weekly
    assert reader.get("/api/gercek/dagilim").json()["report"] == weekly
    assert reader.get("/api/gercek/getiri").json()["report"] == monthly


@pytest.mark.parametrize(
    ("slug", "title"),
    [("haftalik", "Haftalık rapor"), ("aylik", "Aylık rapor"), ("maas-gunu", "Maaş günü")],
)
def test_report_texts_are_the_telegram_texts(
    reader: ApiClient, site: Settings, slug: str, title: str
) -> None:
    real = profile_settings(site)["real"]
    if slug == "maas-gunu":
        text = payday_text(real, NOW)
    else:
        text = report_text(real, NOW, "weekly" if slug == "haftalik" else "monthly")
    assert reader.get(f"/api/gercek/raporlar/{slug}").json() == {"title": title, "text": text}


def test_the_overview_has_class_names_the_refresh_state_and_the_value_chart(
    reader: ApiClient,
) -> None:
    page = reader.get("/api/gercek/ozet").json()

    assert page["class_names"] == CLASS_NAMES
    assert page["stale"] == {}
    # İstanbul'da Çarşamba 12:30 ve bugün fiyat işi yok: elle güncelleme açık.
    assert page["refresh"] == {"allowed": True, "reason": None, "earliest": None, "last_sync": None}
    assert page["chart"]["points"][0] == {
        "day": "2026-11-04",
        "value": "2500",
        "invested": "2500",
        "adjusted": "2500",
        "cpi_period": "2026-10",
        "estimated": False,
    }
    assert page["chart"]["real_gap"] == "107"


def test_the_returns_page_has_the_contributions(reader: ApiClient) -> None:
    contributions = reader.get("/api/gercek/getiri").json()["contributions"]
    assert len(contributions) == 12
    assert {"month", "invested", "planned"} == set(contributions[-1])


def test_a_transaction_row_is_exact_and_canonical(reader: ApiClient) -> None:
    table = reader.get("/api/gercek/islemler").json()["table"]

    assert table["rows"][0] == {
        "id": 4,
        "instrument": "XHT",
        "trade_date": "2026-11-25",
        "side": "BUY",
        "units": "10",
        "unit_price": "11",
        "fee": "0",
        "amount": "110",
        "asset_class": "hisse",
        "class_name": "Hisse",
        "external_ref": None,
        "note": None,
        "created_at": "2026-11-30T09:00:00+00:00",
        "voided_at": None,
        "void_reason": None,
    }
    assert (table["sort"], table["descending"], table["page_size"]) == ("tarih", True, 25)
    assert [column["key"] for column in table["columns"]] == [
        "tarih",
        "fon",
        "tur",
        "adet",
        "tutar",
        "no",
    ]
    assert [(c["key"], c["default"]) for c in table["choices"]] == [
        ("fon", None),
        ("sinif", None),
        ("tur", None),
        ("iptal", "goster"),
    ]
    assert (table["day_filter"], table["search"]) == (True, True)


def test_the_default_sort_is_reported_while_another_column_is_sorted(reader: ApiClient) -> None:
    table = reader.get("/api/gercek/islemler?sirala=fon").json()["table"]

    assert (table["sort"], table["descending"]) == ("fon", False)
    assert (table["default_sort"], table["default_descending"]) == ("tarih", True)


def test_sorting_is_by_decimal_and_ties_keep_number_order(reader: ApiClient) -> None:
    # Tutarlar: #1 1000, #2 1000, #3 500, #4 110.
    assert row_ids(reader, "?sirala=tutar&yon=artan") == [4, 3, 1, 2]
    assert row_ids(reader, "?siralama=tutar.azalan") == [2, 1, 3, 4]


def test_a_filter_is_applied_and_reported_as_a_removable_chip(reader: ApiClient) -> None:
    table = reader.get("/api/gercek/islemler?fon=XHT").json()["table"]

    assert [row["id"] for row in table["rows"]] == [4, 1]
    assert table["params"] == {"fon": "XHT"}
    assert table["active"] == [{"key": "fon", "name": "Fon", "value": "XHT", "day": False}]


def test_search_ignores_case_and_days_bound_the_rows(reader: ApiClient) -> None:
    assert row_ids(reader, "?ara=xht") == [4, 1]
    table = reader.get("/api/gercek/islemler?bas=2026-11-20").json()["table"]
    assert [row["id"] for row in table["rows"]] == [4]
    assert table["active"] == [
        {"key": "bas", "name": "Başlangıç", "value": "2026-11-20", "day": True}
    ]


def test_parameters_that_are_not_understood_are_ignored_and_reported(reader: ApiClient) -> None:
    table = reader.get("/api/gercek/islemler?yok=1&sayfa=abc&bas=2026-11-26&bit=2026-11-01").json()[
        "table"
    ]

    assert table["total"] == 4
    assert table["ignored"] == "yok=1, bas=2026-11-26, bit=2026-11-01, sayfa=abc"


def test_holdings_are_sorted_by_value_and_named(reader: ApiClient) -> None:
    page = reader.get("/api/gercek/varliklar").json()

    assert [row["instrument"] for row in page["table"]["rows"]] == ["XHT", "XPP", "XAC"]
    assert page["table"]["rows"][0]["class_name"] == "Hisse"
    assert page["logical_date"] == "2026-11-25"


def test_a_lot_carries_its_gain(reader: ApiClient) -> None:
    rows = reader.get("/api/gercek/varliklar/lotlar").json()["table"]["rows"]
    assert rows[0] == {
        "instrument": "XAC",
        "acquired": "2026-11-02",
        "units": "10",
        "cost": "500",
        "value": "502",
        "real_return": "0.004",
        "cpi_period": "2026-10",
        "gain": "2",
    }


def test_the_alerts_page_has_open_alerts_and_the_quiet_period(reader: ApiClient) -> None:
    page = reader.get("/api/gercek/alarmlar").json()
    assert (page["alerts"], page["quiet_ended"], page["class_names"]) == ([], None, CLASS_NAMES)
    assert page["table"]["total"] == 0


def test_the_system_page_shows_checks_without_job_details(reader: ApiClient) -> None:
    page = reader.get("/api/gercek/sistem").json()

    names = [check["name"] for check in page["checks"]]
    assert names[:3] == ["SQLite", "Veritabanı şeması", "Config"]
    assert {check["status"] for check in page["checks"]} <= {"ok", "warn", "fail"}
    assert page["backups"] == []
    assert "detail" not in RunItem.model_fields


def test_without_versions_the_settings_come_from_the_portfolio_file(reader: ApiClient) -> None:
    page = reader.get("/api/gercek/ayarlar").json()

    assert page["current"] == {
        "payday": 15,
        "monthly_contribution": "1000",
        "targets": {"hisse": "0.6", "dusuk_risk": "0.4"},
    }
    assert (page["current_id"], page["current_from"], page["planned"]) == (None, None, [])
    assert page["class_names"] == {"hisse": "Hisse", "dusuk_risk": "Düşük risk"}


def test_the_settings_page_shows_the_version_in_force_the_plan_and_the_changes(
    reader: ApiClient, site: Settings
) -> None:
    start_settings(site)
    targets = {"hisse": Decimal("0.6"), "dusuk_risk": Decimal("0.4")}
    with SqliteUnitOfWork(site.db_path) as uow:
        uow.settings.add(
            SettingVersion(date(2027, 1, 1), 15, Decimal(1200), targets), source="web", at=NOW.now()
        )

    page = reader.get("/api/gercek/ayarlar").json()

    assert (page["current_id"], page["current_from"]) == (1, None)
    [planned] = page["planned"]
    assert planned["effective_from"] == "2027-01-01"
    assert planned["values"]["monthly_contribution"] == "1200"
    assert (planned["state"], planned["state_label"], planned["source_label"]) == (
        "planned",
        "planlandı",
        "Web",
    )
    assert planned["changes"] == [{"setting": "Aylık katkı", "change": "1.000,00 TL → 1.200,00 TL"}]
    initial = page["table"]["rows"][1]
    assert (initial["initial"], initial["state"]) == (True, "in_force")
    assert initial["changes"] == [
        {"setting": "Maaş günü", "change": "15"},
        {"setting": "Aylık katkı", "change": "1.000,00 TL"},
        {"setting": "Hedefler", "change": "Hisse %60, Düşük risk %40"},
    ]
    assert reader.get("/api/sanal/ayarlar").json()["planned"] == []


def test_the_fund_options_for_buying_and_selling(reader: ApiClient) -> None:
    funds = [{"code": code, "name": code} for code in ("XAC", "XHT", "XPP")]
    assert reader.get("/api/gercek/secenekler").json() == {"buy": funds, "sell": funds}


def test_a_page_that_cannot_load_is_a_503_with_the_reason(
    site: Settings, keys: FakeAccessKeys
) -> None:
    reader = reader_for(site.model_copy(update={"portfolio_path": None}), keys)

    response = reader.get("/api/gercek/ozet")

    assert (response.status_code, response.json()) == (
        503,
        {"error": "FT_PORTFOLIO_PATH tanımlı değil.", "fields": {}},
    )
    # Sınıf adı yalnız gösterim içindir; işlemler portföy dosyası olmadan da açılır.
    assert reader.get("/api/gercek/islemler").status_code == 200


def test_a_broken_portfolio_file_is_a_503(site: Settings, keys: FakeAccessKeys) -> None:
    assert site.portfolio_path is not None
    site.portfolio_path.write_text("[targets]\nhisse = 0.5\n", encoding="utf-8")

    response = reader_for(site, keys).get("/api/gercek/dagilim")

    assert response.status_code == 503
    assert response.json()["error"]


def test_an_alert_event_and_a_job_run_are_shown_without_the_job_detail(
    reader: ApiClient, site: Settings
) -> None:
    opened = datetime(2026, 11, 21, 18, 35, tzinfo=UTC)
    with SqliteUnitOfWork(site.db_path) as uow:
        uow.allocation_state.end_quiet(date(2026, 11, 20))
        uow.alerts.save(AlertState("drift:hisse", "below", opened, None, opened, "{}"))
        uow.alerts.add_event(
            AlertEvent("drift:hisse", "opened", "below", Decimal("-0.0712"), opened)
        )
        run = uow.runs.start(
            "sync-prices", date(2026, 11, 24), at=datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
        )
        uow.runs.finish(run, "ok", "ayrıntı metni", at=datetime(2026, 11, 24, 9, 1, tzinfo=UTC))

    alerts = reader.get("/api/gercek/alarmlar").json()
    system = reader.get("/api/gercek/sistem")

    assert alerts["quiet_ended"] == "2026-11-20"
    assert [(a["asset_class"], a["direction"]) for a in alerts["alerts"]] == [("hisse", "below")]
    assert alerts["table"]["rows"] == [
        {
            "id": 1,
            "occurred_at": "2026-11-21T18:35:00+00:00",
            "day": "2026-11-21",
            "kind": "opened",
            "direction": "below",
            "deviation": "-0.0712",
            "asset_class": "hisse",
            "class_name": "Hisse",
            "notified_at": None,
        }
    ]
    assert system.json()["table"]["rows"] == [
        {
            "id": 1,
            "job": "sync-prices",
            "logical_date": "2026-11-24",
            "started_at": "2026-11-24T09:00:00+00:00",
            "finished_at": "2026-11-24T09:01:00+00:00",
            "status": "ok",
            "status_label": "Tamam",
        }
    ]
    assert "ayrıntı metni" not in system.text
