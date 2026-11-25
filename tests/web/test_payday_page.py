"""Sanal maaş günü planı panelden: önizleme yazmaz, onay CLI'nin yazacağı alımları yazar; gerçek
profilde adres yoktur (K-113, K-119, K-125, K-126)."""

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans import bootstrap
from finans.cli.main import app as ft_app
from tests.fakes.clock import FixedClock
from tests.support.web_browser import hidden_fields
from tests.support.web_writes import NOW, SANAL, Site, cli_rows, cli_twin, post_confirm, same_row

PAGE = "/sanal/maas-gunu"
SAVE = "/sanal/islemler/kaydet"


def test_the_last_payday_plan_is_previewed_then_applied_as_the_cli_would(
    site: Site, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = site.browser()

    page = me.get(PAGE)

    assert page.status_code == 200, page.text
    assert 'name="maas_gunu" type="date" value="2026-11-15"' in page.text
    assert "2026-11-20 fiyatıyla 57 pay × 10,5 TL = 598,50 TL; artan 1,50 TL." in page.text
    assert "2026-11-20 fiyatıyla 20 pay × 20 TL = 400,00 TL; artan 0,00 TL." in page.text
    assert SANAL in page.text
    assert "Planı uygula (2 alım)" in page.text
    assert site.rows("sanal") == []

    saved = me.post(SAVE, hidden_fields(page.text, SAVE))

    assert saved.headers["location"] == "/sanal/islemler?islem=maas-gunu&no=2"
    assert "Maaş günü planı uygulandı: 2 sanal alım." in me.get(saved.headers["location"]).text
    again = me.get(PAGE).text
    assert again.count("Zaten uygulandı.") == 2
    assert "Planı uygula" not in again
    twin = cli_twin(tmp_path)
    monkeypatch.setattr(bootstrap, "system_clock", lambda: FixedClock(NOW))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(twin.portfolio_path))
    monkeypatch.setenv("FT_DB_PATH", str(twin.db_path))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(twin.sanal_database))
    monkeypatch.setenv("FT_PROFILE", "sanal")
    command = ["sanal", "maas-gunu-uygula", "--maas-gunu", "2026-11-15"]
    assert CliRunner().invoke(ft_app, command, input="e\n").exit_code == 0
    web, cli = site.rows("sanal"), cli_rows(twin, "sanal")
    assert [(same_row(s), s.external_ref) for s in web] == [
        (same_row(s), s.external_ref) for s in cli
    ]


def test_a_voided_purchase_is_offered_again_only_when_asked(site: Site) -> None:
    me = site.browser()
    page = me.get(PAGE)
    me.post(SAVE, hidden_fields(page.text, SAVE))
    post_confirm(me, "sanal", me.post("/sanal/islemler/1/iptal", {"gerekce": "deneme"}))

    plain = me.post(PAGE, {"maas_gunu": "2026-11-15"})
    again = me.post(PAGE, {"maas_gunu": "2026-11-15", "iptaller": "1"})

    assert "İptal edilmiş bir alımı var" in plain.text
    assert "Planı uygula" not in plain.text
    assert "Planı uygula (1 alım)" in again.text
    assert me.post(SAVE, hidden_fields(again.text, SAVE)).status_code == 303
    assert len(site.rows("sanal")) == 3


def test_a_payday_outside_the_price_window_records_nothing(site: Site) -> None:
    page = site.browser().post(PAGE, {"maas_gunu": "2026-10-15"})

    assert page.status_code == 200
    assert "Planı uygula" not in page.text
    assert "Uygulanacak alım yok." in page.text


def test_a_bad_day_keeps_the_form_and_says_what_to_fix(site: Site) -> None:
    page = site.browser().post(PAGE, {"maas_gunu": "15.11.2026"})

    assert page.status_code == 400
    assert "Tarih YYYY-AA-GG biçiminde olmalı" in page.text
    assert 'aria-invalid="true"' in page.text


def test_a_signed_payday_cannot_be_replayed_on_the_real_profile(site: Site) -> None:
    me = site.browser()
    fields = hidden_fields(me.get(PAGE).text, SAVE)

    assert me.post("/gercek/islemler/kaydet", fields).status_code == 403
    assert me.get("/gercek/maas-gunu").status_code == 404
    assert "/maas-gunu" not in me.get("/gercek/islemler").text
    assert 'href="/sanal/maas-gunu"' in me.get("/sanal/islemler").text


def test_a_locked_session_is_sent_to_the_lock_page(site: Site) -> None:
    response = site.browser(unlocked=False).get(PAGE)

    assert response.headers["location"] == f"/sanal/kilit?sonra={PAGE}"


def test_the_log_holds_only_the_count_and_profile(
    site: Site, caplog: pytest.LogCaptureFixture
) -> None:
    me = site.browser()
    page = me.get(PAGE)
    with caplog.at_level(logging.INFO, logger="finans.web"):
        me.post(SAVE, hidden_fields(page.text, SAVE))

    logged = [r.getMessage() for r in caplog.records if r.name == "finans.web"]
    assert logged == ["Maaş günü planı uygulandı: 2 alım (sanal)"]
