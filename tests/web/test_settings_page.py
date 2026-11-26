"""Web'de ayarlar (K-127): geçerli ayar ve geçmiş, yüzdeyle hedef, sanal portföye de uygulama,
sonraki sürümlere taşıma ve vazgeçme; önizleme yazmaz, onay imzalı ve tek kullanımlık (K-126)."""

import logging
import re
from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from finans import bootstrap
from finans.adapters.sqlite import connection as sqlite_connection
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.settings import effective_config
from finans.domain.settings import SettingVersion
from finans.ports.repositories import StoredSetting
from finans.settings import Profile
from tests.fakes.clock import FixedClock
from tests.support.web_browser import Browser, hidden_fields, only_app_script
from tests.support.web_writes import (
    GERCEK,
    NOW,
    SANAL,
    Site,
    cli_twin,
    make_site,
    run_cli,
    start_settings,
)

D = Decimal
FORM = {
    "gun": "2026-12-01",
    "maas_gunu": "15",
    "katki": "1000",
    "hedef_hisse": "60",
    "hedef_dusuk_risk": "40",
    "onceki_maas_gunu": "15",
    "onceki_katki": "1000",
    "onceki_hedef_hisse": "60",
    "onceki_hedef_dusuk_risk": "40",
}
CONFIRM: dict[Profile, str] = {"real": "/gercek/ayarlar/kaydet", "sanal": "/sanal/ayarlar/kaydet"}
START = SettingVersion(date.min, 15, D(1000), {"hisse": D("0.6"), "dusuk_risk": D("0.4")})
JANUARY = replace(START, effective_from=date(2027, 1, 1), monthly_contribution=D(1200))
MARCH = replace(
    START, effective_from=date(2027, 3, 1), targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")}
)


def _add(site: Site, profile: Profile, version: SettingVersion) -> None:
    conf = site.conf(profile)
    with SqliteUnitOfWork(conf.db_path, sanal=profile == "sanal") as uow:
        uow.settings.add(version, source="web", at=NOW)


def _rows(site: Site, profile: Profile) -> list[StoredSetting]:
    conf = site.conf(profile)
    with SqliteUnitOfWork(conf.db_path, readonly=True, sanal=profile == "sanal") as uow:
        return uow.settings.list()


def _contribution_and_targets(site: Site, on: date) -> tuple[Decimal | None, dict[str, Decimal]]:
    conf = site.conf("real")
    assert conf.portfolio_path is not None
    config = bootstrap.portfolio_source().load(conf.portfolio_path)
    with SqliteUnitOfWork(conf.db_path, readonly=True) as uow:
        in_force = effective_config(uow, config, on=on)
    return in_force.monthly_contribution, dict(in_force.targets)


def _confirm(me: Browser, page: str, **extra: str) -> httpx.Response:
    return me.post(CONFIRM["real"], {**hidden_fields(page, CONFIRM["real"]), **extra})


@pytest.fixture
def started(site: Site) -> Site:
    start_settings(site.settings)
    return site


def test_the_page_shows_the_setting_in_force_the_plan_and_the_history(started: Site) -> None:
    _add(started, "real", JANUARY)

    page = started.browser().get("/gercek/ayarlar").text

    assert "Başlangıç (portfolio.toml)" in page
    assert "0001" not in page
    assert "ayın 15. günü" in page
    assert "1.000,00 TL" in page
    assert '<dt>Düşük risk</dt><dd class="num">%40</dd>' in page
    assert "1 Ocak 2027&#39;den itibaren" in page
    assert "Aylık katkı: 1.000,00 TL → 1.200,00 TL" in page
    assert 'href="/gercek/ayarlar/2/vazgec"' in page
    assert 'href="/gercek/ayarlar/yeni"' in page


def test_targets_are_entered_in_percent_stored_as_ratios_and_match_the_cli(
    started: Site, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = started.browser()
    form = me.get("/gercek/ayarlar/yeni").text
    assert 'id="hedef_hisse" name="hedef_hisse" type="text" value="60"' in form
    assert "data-hedef" in form
    assert '<p class="target-total" id="hedef-toplam" aria-live="polite">Toplam %100</p>' in form

    retargeted = {**FORM, "hedef_hisse": "70", "hedef_dusuk_risk": "30"}
    preview = me.post("/gercek/ayarlar/yeni", retargeted)

    assert preview.status_code == 200, preview.text
    assert GERCEK in preview.text
    assert "<dt>Hedefler</dt><dd>Hisse %60 → %70, Düşük risk %40 → %30</dd>" in preview.text
    assert "Gerçek ayarı kaydet" in preview.text
    assert 'name="sonrakilere"' not in preview.text
    assert len(_rows(started, "real")) == 1
    saved = _confirm(me, preview.text)
    assert saved.headers["location"] == "/gercek/ayarlar?islem=ayar&no=2"
    assert "Ayar sürümü #2 kaydedildi." in me.get(saved.headers["location"]).text
    web_row = _rows(started, "real")[-1]
    assert (web_row.source, web_row.version.targets) == (
        "web",
        {"hisse": D("0.7"), "dusuk_risk": D("0.3")},
    )

    twin = cli_twin(tmp_path)
    start_settings(twin)
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(twin.portfolio_path))
    monkeypatch.setattr(bootstrap, "system_clock", lambda: FixedClock(NOW))
    args = ["ayar", "hedef", "hisse=0.7", "dusuk_risk=0.3", "--tarih", "2026-12-01"]
    run_cli(twin, "real", args, monkeypatch)
    with SqliteUnitOfWork(twin.db_path, readonly=True) as uow:
        cli_row = uow.settings.list()[-1]
    assert (cli_row.version, cli_row.recorded_at) == (web_row.version, web_row.recorded_at)


@pytest.mark.parametrize(
    ("change", "field_error", "total"),
    [
        (
            {"hedef_dusuk_risk": "37,5"},
            "Hedeflerin toplamı %97,5; %2,5 eksik. Toplam tam %100 olmalı.",
            "Toplam %97,5 · %2,5 eksik",
        ),
        (
            {"hedef_dusuk_risk": "42,5"},
            "Hedeflerin toplamı %102,5; %2,5 fazla. Toplam tam %100 olmalı.",
            "Toplam %102,5 · %2,5 fazla",
        ),
        (
            {"hedef_dusuk_risk": "37.5"},
            "Düşük risk: nokta kullanılmaz; ondalık ayırıcı virgüldür (1,5), binlik ayırıcı"
            " yazılmaz (5000).",
            "Toplam %? · bir alan sayı değil",
        ),
    ],
)
def test_a_total_other_than_one_hundred_is_refused_with_the_gap(
    started: Site, change: dict[str, str], field_error: str, total: str
) -> None:
    refused = started.browser().post("/gercek/ayarlar/yeni", {**FORM, **change})

    assert refused.status_code == 400
    assert field_error in refused.text
    assert total in refused.text
    assert len(_rows(started, "real")) == 1


def test_untouched_settings_keep_the_value_in_force_on_the_chosen_day(started: Site) -> None:
    _add(started, "real", JANUARY)
    me = started.browser()
    retargeted = {**FORM, "gun": "2027-02-01", "hedef_hisse": "70", "hedef_dusuk_risk": "30"}

    preview = me.post("/gercek/ayarlar/yeni", retargeted)
    _confirm(me, preview.text)

    assert "<dt>Aylık katkı</dt>" not in preview.text
    assert _rows(started, "real")[-1].version == replace(
        JANUARY,
        effective_from=date(2027, 2, 1),
        targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")},
    )


def test_the_real_form_can_also_write_the_sanal_portfolio_and_shows_each_result(
    started: Site,
) -> None:
    me = started.browser()
    assert "Sanal portföye de uygula" in me.get("/gercek/ayarlar/yeni").text
    assert "Sanal portföye de uygula" not in me.get("/sanal/ayarlar/yeni").text

    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200", "sanala": "1"})
    assert preview.status_code == 200, preview.text
    assert "<h2>Gerçek portföy</h2>" in preview.text
    assert "<h2>Sanal portföy</h2>" in preview.text
    assert GERCEK in preview.text
    assert SANAL in preview.text
    assert "İki portföye de kaydet" in preview.text

    result = _confirm(me, preview.text).text

    assert "<strong>Gerçek:</strong> ayar sürümü #2 kaydedildi." in result
    assert "<strong>Sanal:</strong> ayar sürümü #2 kaydedildi." in result
    assert _rows(started, "real")[-1].version.monthly_contribution == D(1200)
    assert _rows(started, "sanal")[-1].version.monthly_contribution == D(1200)


def test_when_the_sanal_settings_change_after_the_preview_only_the_real_one_is_written(
    started: Site,
) -> None:
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200", "sanala": "1"})
    _add(started, "sanal", replace(START, effective_from=NOW.date(), payday=20))

    result = _confirm(me, preview.text).text

    assert "<strong>Gerçek:</strong> ayar sürümü #2 kaydedildi." in result
    changed = "<strong>Sanal: yazılmadı.</strong> Önizlemeden sonra bu portföyün ayarları değişti."
    assert changed in result
    assert [row.source for row in _rows(started, "sanal")] == ["toml", "web"]
    assert _rows(started, "real")[-1].version.monthly_contribution == D(1200)


def test_a_busy_sanal_database_can_be_retried_without_writing_the_real_one_twice(
    started: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite_connection, "BUSY_TIMEOUT_MS", 50)
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200", "sanala": "1"})

    with closing(connect(started.conf("sanal").db_path, sanal=True)) as job:
        job.execute("BEGIN IMMEDIATE")
        busy = _confirm(me, preview.text).text
        job.execute("ROLLBACK")

    assert "<strong>Sanal: yazılmadı.</strong> Şu an zamanlanmış bir iş çalışıyor." in busy
    assert len(_rows(started, "sanal")) == 1
    retried = me.post(CONFIRM["real"], hidden_fields(busy, CONFIRM["real"])).text
    assert "<strong>Gerçek:</strong> bu onay zaten kullanılmıştı; ayar sürümü #2" in retried
    assert "<strong>Sanal:</strong> ayar sürümü #2 kaydedildi." in retried
    assert len(_rows(started, "real")) == 2


@pytest.mark.parametrize(("carry", "in_march"), [(False, D(1000)), (True, D(1200))])
def test_a_january_contribution_lasts_past_a_planned_march_change_only_when_carried(
    started: Site, carry: bool, in_march: Decimal
) -> None:
    _add(started, "real", MARCH)
    me = started.browser()

    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "gun": "2027-01-01", "katki": "1200"})
    if carry:
        carried = _confirm(me, preview.text, sonrakilere="1")
        assert "kaydedilince ona da taşınacak" in carried.text
        _confirm(me, carried.text, sonrakilere="1")
    else:
        _confirm(me, preview.text)

    warning = (
        "Yürürlüğü 1 Mart 2027 olan planlanan sürüm (#2) bu değişikliği taşımıyor; o günden"
        " itibaren aylık katkı 1.000,00 TL olur."
    )
    assert warning in preview.text
    assert '<input type="checkbox" name="sonrakilere" value="1">' in preview.text
    listed = "Gerçek #2 · 1 Mart 2027&#39;den itibaren: Aylık katkı 1.000,00 TL → 1.200,00 TL"
    assert listed in preview.text
    assert _contribution_and_targets(started, date(2027, 3, 15)) == (in_march, MARCH.targets)
    if carry:
        assert _rows(started, "real")[1].cancel_reason == "yeni değişiklik taşındı: #3"


@pytest.mark.parametrize("previewed_carry", [False, True])
def test_a_carry_choice_other_than_the_previewed_one_saves_nothing_and_previews_again(
    started: Site, previewed_carry: bool
) -> None:
    """Kutu imzasızdır, önizlenen seçim imzalıdır; farklı gönderilen seçim kaydedilmez."""
    _add(started, "real", MARCH)
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "gun": "2027-01-01", "katki": "1200"})
    if previewed_carry:
        preview = _confirm(me, preview.text, sonrakilere="1")
    assert ("checked" in preview.text.split('name="sonrakilere"')[1][:20]) is previewed_carry

    flipped = _confirm(me, preview.text, **({} if previewed_carry else {"sonrakilere": "1"}))

    assert flipped.status_code == 200
    assert "Kutunun seçimi önizlemedekinden farklı; kayıt yapılmadı." in flipped.text
    assert len(_rows(started, "real")) == 2
    expected_box = "" if previewed_carry else " checked"
    assert f'name="sonrakilere" value="1"{expected_box}>' in flipped.text


def test_a_planned_version_is_cancelled_with_a_reason_and_its_row_stays(started: Site) -> None:
    _add(started, "real", JANUARY)
    me = started.browser()
    assert 'name="gerekce"' in me.get("/gercek/ayarlar/2/vazgec").text
    empty = me.post("/gercek/ayarlar/2/vazgec", {"gerekce": " "})
    assert empty.status_code == 400
    assert "Gerekçe boş bırakılamaz; neden vazgeçildiği kayıtta kalır." in empty.text

    preview = me.post("/gercek/ayarlar/2/vazgec", {"gerekce": "yanlış tutar"})
    assert GERCEK in preview.text
    assert _rows(started, "real")[1].cancelled_at is None
    saved = me.post(CONFIRM["real"], hidden_fields(preview.text, CONFIRM["real"]))

    assert saved.headers["location"] == "/gercek/ayarlar?islem=ayar-vazgec&no=2"
    assert "Ayar sürümü #2 için vazgeçildi." in me.get(saved.headers["location"]).text
    assert _rows(started, "real")[1].cancel_reason == "yanlış tutar"
    in_force = me.get("/gercek/ayarlar/1/vazgec")
    assert in_force.status_code == 409
    assert "1 numaralı ayar sürümü yürürlüğe girmiş; vazgeçilemez." in in_force.text


def test_a_change_before_the_first_config_apply_is_refused_on_the_form(site: Site) -> None:
    refused = site.browser().post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200"})

    assert refused.status_code == 409
    assert "Ayarların başlangıç sürümü yok; önce `ft config apply` çalıştır." in refused.text


def test_the_log_says_which_setting_changed_but_no_amount(
    started: Site, caplog: pytest.LogCaptureFixture
) -> None:
    me = started.browser()
    with caplog.at_level(logging.INFO, logger="finans"):
        preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200"})
        _confirm(me, preview.text)

    logged = [r.getMessage() for r in caplog.records if r.name in ("finans.web", "finans.sunum")]
    assert logged == ["Ayar sürümü kaydedildi: #2 aylık katkı; sonraki sürümlere taşınan: 0 (real)"]


def test_a_save_while_a_job_holds_the_database_can_be_retried(
    started: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite_connection, "BUSY_TIMEOUT_MS", 50)
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200"})

    with closing(connect(started.conf("real").db_path)) as job:
        job.execute("BEGIN IMMEDIATE")
        busy = _confirm(me, preview.text)
        job.execute("ROLLBACK")

    assert busy.status_code == 503
    assert 'href="/gercek/ayarlar">Geri dön</a>' in busy.text
    assert len(_rows(started, "real")) == 1
    retried = me.post(CONFIRM["real"], hidden_fields(busy.text, CONFIRM["real"]))
    assert retried.status_code == 303


def test_a_locked_session_is_sent_to_the_lock_page(started: Site) -> None:
    me = started.browser(unlocked=False)

    response = me.get("/gercek/ayarlar/yeni")

    assert response.status_code == 303
    assert response.headers["location"] == "/gercek/kilit?sonra=/gercek/ayarlar/yeni"
    assert me.get("/gercek/ayarlar").status_code == 200


@pytest.mark.parametrize(
    "path", ["/gercek/ayarlar/yeni", "/gercek/ayarlar/kaydet", "/gercek/ayarlar/2/vazgec"]
)
def test_every_settings_post_checks_origin_and_token(started: Site, path: str) -> None:
    me = started.browser()

    assert me.post(path, FORM, headers={}).status_code == 403
    assert me.post(path, FORM, token="0" * 64).status_code == 403


def test_without_a_password_hash_the_page_offers_no_writing(
    tmp_path: Path, migrated_db: Path
) -> None:
    site = make_site(tmp_path, migrated_db, stored=None)
    start_settings(site.settings)

    page = site.browser(unlocked=False).get("/gercek/ayarlar").text

    assert "Yazma bu cihazda kurulmadı." in page
    assert "/ayarlar/yeni" not in page


@pytest.mark.parametrize(
    "path",
    ["/gercek/ayarlar", "/gercek/ayarlar/yeni", "/sanal/ayarlar/yeni", "/gercek/ayarlar/2/vazgec"],
)
def test_settings_pages_keep_the_page_rules(started: Site, path: str) -> None:
    """K-128: tek h1, satır içi stil ve betik yok, her alanın etiketi var."""
    _add(started, "real", JANUARY)

    page = started.browser().get(path).text

    assert page.count("<h1") == 1
    assert "style=" not in page
    assert only_app_script(page)
    for field in re.findall(r'<(?:input|select|textarea) id="([^"]+)"', page):
        assert f'<label for="{field}">' in page


def test_the_same_confirmation_twice_shows_the_first_record(started: Site) -> None:
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200"})
    assert _confirm(me, preview.text).status_code == 303

    again = _confirm(me, preview.text)

    assert again.status_code == 409
    assert "Bu onay zaten kullanıldı; ayar sürümü #2 olarak kaydedildi." in again.text
    assert len(_rows(started, "real")) == 2


def test_a_change_after_the_preview_shows_a_new_preview_and_saves_nothing(started: Site) -> None:
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200"})
    _add(started, "real", replace(START, effective_from=NOW.date(), payday=20))

    changed = _confirm(me, preview.text)

    assert changed.status_code == 409
    assert "Önizlemeden sonra veriler değişti; kayıt yapılmadı." in changed.text
    assert "<dt>Aylık katkı</dt><dd>1.000,00 TL → 1.200,00 TL</dd>" in changed.text
    assert len(_rows(started, "real")) == 2
    assert _confirm(me, changed.text).status_code == 303


def test_edit_returns_to_the_form_with_what_was_entered(started: Site) -> None:
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200", "sanala": "1"})

    edit = me.post("/gercek/ayarlar/yeni", hidden_fields(preview.text, "/gercek/ayarlar/yeni"))

    assert edit.status_code == 200
    assert 'id="katki" name="katki" type="text" value="1200"' in edit.text
    assert 'name="sanala" value="1" checked' in edit.text


def test_a_tampered_or_foreign_confirmation_is_refused(started: Site) -> None:
    me = started.browser()
    preview = me.post("/gercek/ayarlar/yeni", {**FORM, "katki": "1200"})
    signed = hidden_fields(preview.text, CONFIRM["real"])

    tampered = me.post(CONFIRM["real"], {**signed, "katki": "120000"})
    foreign = me.post(CONFIRM["sanal"], signed)

    assert (tampered.status_code, foreign.status_code) == (403, 403)
    assert len(_rows(started, "real")) == 1
    assert len(_rows(started, "sanal")) == 1


def test_a_cancellation_confirmed_twice_shows_the_first_one(started: Site) -> None:
    _add(started, "real", JANUARY)
    me = started.browser()
    preview = me.post("/gercek/ayarlar/2/vazgec", {"gerekce": "yanlış tutar"})
    assert me.post(CONFIRM["real"], hidden_fields(preview.text, CONFIRM["real"])).status_code == 303

    again = me.post(CONFIRM["real"], hidden_fields(preview.text, CONFIRM["real"]))

    assert again.status_code == 409
    assert "Bu onay zaten kullanıldı; ayar sürümü #2 için vazgeçildi." in again.text
