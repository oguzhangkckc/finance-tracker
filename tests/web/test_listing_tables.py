"""Varlıklar, Lotlar, Alarm geçmişi ve İş geçmişi tabloları (K-129)."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.ports.repositories import AlertEvent, JobStatus
from tests.support.web_browser import only_app_script
from tests.support.web_writes import Site

FUND = re.compile(r'<td data-label="Fon"><strong>(\w+)</strong></td>')
NUMBER = re.compile(r'<td data-label="#">(\d+)</td>')
EVENING = datetime(2026, 11, 21, 15, 35, tzinfo=UTC)
TABLE_PAGES = (
    "/gercek/varliklar",
    "/gercek/varliklar/lotlar",
    "/gercek/alarmlar",
    "/gercek/sistem",
)


def _funds(site: Site, path: str) -> list[str]:
    return FUND.findall(site.browser().get(path).text)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", ["XHT", "XPP", "XAC"]),
        ("?sirala=fon&yon=artan", ["XAC", "XHT", "XPP"]),
        ("?siralama=adet.artan", ["XAC", "XPP", "XHT"]),
        ("?dagilim=disi", ["XAC"]),
        ("?sinif=dusuk_risk", ["XPP"]),
        ("?ara=xh", ["XHT"]),
    ],
)
def test_holdings_sort_by_value_and_filter_by_class_and_allocation(
    site: Site, query: str, expected: list[str]
) -> None:
    assert _funds(site, f"/gercek/varliklar{query}") == expected


def test_each_holding_links_to_its_lots(site: Site) -> None:
    page = site.browser().get("/gercek/varliklar").text

    link = '<a href="/gercek/varliklar/lotlar?fon=XHT">Lotlar<span class="sr"> (XHT)</span></a>'
    assert link in page
    assert '<option value="dusuk_risk">Düşük risk</option>' in page


def test_lots_filter_by_fund_and_day_and_show_the_gain(site: Site) -> None:
    me = site.browser()

    page = me.get("/gercek/varliklar/lotlar?fon=XHT").text
    later = me.get("/gercek/varliklar/lotlar?fon=XHT&bas=2026-11-20").text

    days = re.findall(r'<td data-label="Alış günü">([^<]+)</td>', page)
    assert days == ["2 Kasım", "25 Kasım"]
    assert '<td data-label="Kâr/zarar" class="num">100,00 TL</td>' in page
    assert re.findall(r'<td data-label="Alış günü">([^<]+)</td>', later) == ["25 Kasım"]


def _events(site: Site) -> None:
    events = [
        AlertEvent("drift:hisse", "opened", "below", Decimal("-0.06"), EVENING),
        AlertEvent(
            "drift:dusuk_risk", "opened", "above", Decimal("0.07"), EVENING + timedelta(minutes=1)
        ),
        AlertEvent(
            "drift:hisse", "resolved", "below", Decimal("-0.02"), EVENING + timedelta(days=2)
        ),
    ]
    with SqliteUnitOfWork(site.conf("real").db_path) as uow:
        ids = [uow.alerts.add_event(event) for event in events]
        uow.alerts.mark_notified(ids[:2], at=EVENING + timedelta(minutes=5))


def test_the_alert_history_lists_events_newest_first_with_delivery(site: Site) -> None:
    _events(site)

    page = site.browser().get("/gercek/alarmlar").text

    times = re.findall(r'<td data-label="Tarih">([^<]+)</td>', page)
    assert times == ["23 Kasım 18:35", "21 Kasım 18:36", "21 Kasım 18:35"]
    assert '<td data-label="Bildirim">bekliyor</td>' in page
    assert '<td data-label="Bildirim">21 Kasım 18:40</td>' in page
    assert '<td data-label="Sınıf">Düşük risk</td>' in page


@pytest.mark.parametrize(
    ("query", "classes"),
    [
        ("?olay=kapandi", ["Hisse"]),
        ("?sinif=dusuk_risk", ["Düşük risk"]),
        ("?sirala=sapma&yon=azalan", ["Düşük risk", "Hisse", "Hisse"]),
    ],
)
def test_the_alert_history_filters_and_sorts(site: Site, query: str, classes: list[str]) -> None:
    _events(site)

    page = site.browser().get(f"/gercek/alarmlar{query}").text

    assert re.findall(r'<td data-label="Sınıf">([^<]+)</td>', page) == classes


def _runs(site: Site, extra: int = 0) -> None:
    start = datetime(2026, 11, 20, 9, 15, tzinfo=UTC)
    jobs: list[tuple[str, JobStatus]] = [
        ("backup", "ok"),
        ("sync-prices", "partial"),
        ("sync-cpi", "failed"),
    ]
    jobs += [("backup", "ok")] * extra
    with SqliteUnitOfWork(site.conf("real").db_path) as uow:
        for n, (job, status) in enumerate(jobs):
            # Her iş ve gün için tek 'ok' kaydı olabilir (K-12); kayıtlar ayrı günlere düşer.
            at = start + timedelta(days=n)
            run = uow.runs.start(job, at.date(), at=at)
            uow.runs.finish(run, status, "{}", at=at + timedelta(minutes=1))


def test_the_job_history_filters_by_status_and_job_with_turkish_labels(site: Site) -> None:
    _runs(site)
    me = site.browser()

    everything = me.get("/gercek/sistem").text
    failed = me.get("/gercek/sistem?durum=failed").text
    backups = me.get("/gercek/sistem?is=backup").text

    assert [int(n) for n in NUMBER.findall(everything)] == [3, 2, 1]
    assert '<span class="warn">Başarısız</span>' in failed
    assert [int(n) for n in NUMBER.findall(failed)] == [3]
    assert [int(n) for n in NUMBER.findall(backups)] == [1]


def test_the_job_history_pages_every_run(site: Site) -> None:
    _runs(site, extra=30)

    first = site.browser().get("/gercek/sistem").text
    second = site.browser().get("/gercek/sistem?sayfa=2").text

    assert "Sayfa 1 / 2 · 33 satır" in first
    assert len(NUMBER.findall(first)) == 25
    assert [int(n) for n in NUMBER.findall(second)][-1] == 1


@pytest.mark.parametrize("path", TABLE_PAGES)
def test_a_misunderstood_parameter_is_named_on_every_table(site: Site, path: str) -> None:
    page = site.browser().get(f"{path}?renk=mavi").text

    assert "Filtre anlaşılmadı: renk=mavi. Yok sayıldı." in page


@pytest.mark.parametrize("path", TABLE_PAGES)
def test_table_pages_keep_the_page_rules(site: Site, path: str) -> None:
    page = site.browser().get(path).text

    assert page.count("<h1") == 1
    assert "style=" not in page
    assert only_app_script(page)
    for field in re.findall(r'<(?:input|select) id="([^"]+)"', page):
        assert f'<label for="{field}">' in page
