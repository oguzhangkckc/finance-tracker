"""İşlemler tablosu: sıralama, filtre ve sayfalama adres parametreleriyle (K-129)."""

import re
from datetime import date
from decimal import Decimal

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.models import Side, Transaction
from tests.support.web_browser import only_app_script
from tests.support.web_writes import NOW, REAL_BUY, Site, post_confirm, post_preview

PAGE = "/gercek/islemler"
NUMBER = re.compile(r'<td data-label="#">(\d+)</td>')


def _numbers(site: Site, query: str = "") -> list[int]:
    page = site.browser().get(f"{PAGE}{query}").text
    return [int(n) for n in NUMBER.findall(page)]


def _add(site: Site, count: int) -> None:
    with SqliteUnitOfWork(site.conf("real").db_path) as uow:
        for n in range(count):
            tx = Transaction("XPP", date(2026, 11, 3), Side.BUY, Decimal(1), Decimal("20.000000"))
            uow.transactions.add(tx, external_ref=None, note=f"ek {n}", created_at=NOW)


def test_the_default_is_newest_first_with_amounts_and_class_names(site: Site) -> None:
    page = site.browser().get(PAGE).text

    assert [int(n) for n in NUMBER.findall(page)] == [4, 3, 2, 1]
    assert '<th aria-sort="descending"><a href="?sirala=tarih&amp;yon=artan">Tarih' in page
    assert '<td data-label="Tutar" class="num">1.000,00 TL</td>' in page
    assert '<strong>XPP</strong> <span class="muted">Düşük risk</span>' in page
    assert only_app_script(page)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?sirala=tutar&yon=azalan", [2, 1, 3, 4]),
        ("?siralama=fon.artan", [3, 1, 4, 2]),
        ("?sirala=no&yon=artan", [1, 2, 3, 4]),
        ("?fon=XHT", [4, 1]),
        ("?sinif=dusuk_risk", [2]),
        ("?bas=2026-11-20", [4]),
        ("?fon=XHT&bit=2026-11-02", [1]),
    ],
)
def test_sorting_and_filters_follow_the_address(
    site: Site, query: str, expected: list[int]
) -> None:
    assert _numbers(site, query) == expected


def test_active_filters_show_as_removable_chips_with_turkish_dates(site: Site) -> None:
    page = site.browser().get(f"{PAGE}?fon=XHT&bas=2026-11-20").text

    assert '<span class="count">· 2 etkin</span>' in page
    assert f'<a href="{PAGE}?bas=2026-11-20">Fon: XHT<span' in page
    assert f'<a href="{PAGE}?fon=XHT">Başlangıç: 20 Kasım<span' in page
    assert f'<a class="clear" href="{PAGE}">Hepsini temizle</a>' in page
    assert '<option value="XHT" selected>XHT</option>' in page


def test_a_filter_without_rows_offers_to_clear(site: Site) -> None:
    page = site.browser().get(f"{PAGE}?tur=satis").text

    assert NUMBER.findall(page) == []
    assert f'Bu filtrelerle işlem yok. <a href="{PAGE}">Filtreleri temizle</a>' in page


def test_receipt_numbers_notes_and_voids_can_be_found(site: Site) -> None:
    me = site.browser()
    post_confirm(me, "real", post_preview(me, "real", "alis", REAL_BUY))
    with SqliteUnitOfWork(site.conf("real").db_path) as uow:
        uow.transactions.void(1, reason="yanlış giriş", at=NOW)

    assert _numbers(site, "?ara=d-1") == [5]
    assert _numbers(site, "?ara=YANLIŞ") == [1]
    assert _numbers(site, "?iptal=gizle") == [5, 4, 3, 2]
    assert _numbers(site, "?iptal=yalniz") == [1]
    assert _numbers(site) == [5, 4, 3, 2, 1]


def test_a_misunderstood_parameter_is_named_and_ignored(site: Site) -> None:
    page = site.browser().get(f"{PAGE}?renk=mavi&sayfa=0").text

    assert "Filtre anlaşılmadı: renk=mavi, sayfa=0. Yok sayıldı." in page
    assert [int(n) for n in NUMBER.findall(page)] == [4, 3, 2, 1]


def test_twenty_five_rows_per_page_with_links_that_keep_the_filters(site: Site) -> None:
    _add(site, 30)

    first = site.browser().get(f"{PAGE}?fon=XPP").text
    second = _numbers(site, "?fon=XPP&sayfa=2")

    assert len(NUMBER.findall(first)) == 25
    assert "Sayfa 1 / 2 · 31 satır" in first
    assert f'rel="next" href="{PAGE}?fon=XPP&amp;sayfa=2"' in first
    assert len(second) == 6
    assert second[-1] == 2


def test_the_saved_notice_still_shows_without_a_filter_note(site: Site) -> None:
    page = site.browser().get(f"{PAGE}?islem=alis&no=4").text

    assert "Alım #4 kaydedildi." in page
    assert "Filtre anlaşılmadı" not in page


def test_the_filter_form_fields_are_labelled(site: Site) -> None:
    page = site.browser().get(PAGE).text

    for field in re.findall(r'<(?:input|select) id="([^"]+)"', page):
        assert f'<label for="{field}">' in page
