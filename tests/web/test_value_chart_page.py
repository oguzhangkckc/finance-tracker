"""Değerin seyri grafiği sayfada (K-129): üç çizgi, reel kazanç ya da kayıp cümlesi, TÜFE'si
açıklanmamış hafta notu ve tablo karşılığı."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.models import PricePoint, Side, Transaction
from tests.support.web_writes import NOW, Site

GAIN = "Değer, enflasyona göre güncellenmiş yatırımın 107,00 TL üstünde: reel kazanç."


def _weeks(page: str) -> list[str]:
    return re.findall(r'<td data-label="Hafta">([^<]+)</td>', page)


def test_the_summary_draws_three_lines_and_says_whether_there_is_a_real_gain(site: Site) -> None:
    page = site.browser().get("/gercek/").text

    assert 'role="img" aria-labelledby="ozet-deger-baslik ozet-deger-aciklama"' in page
    for line in ("line-value", "line-invested", "line-adjusted"):
        assert f'<path class="{line}" d="' in page
    assert "Yatırılan para (net katkı)" in page
    assert "Enflasyona göre güncellenmiş yatırım" in page
    assert GAIN in page
    assert _weeks(page) == ["4 Kasım", "11 Kasım", "18 Kasım", "25 Kasım"]
    assert '<td data-label="Değer" class="num">2.717,00 TL</td>' in page
    assert '<td data-label="Yatırılan para" class="num">2.610,00 TL</td>' in page
    assert "son açıklanan dönem" not in page


def test_a_price_drop_below_the_adjusted_contribution_is_called_a_real_loss(site: Site) -> None:
    # 25 Kasım: XHT 110 × 9 + XPP 50 × 20,1 + XAC 10 × 50,2 = 2497; güncellenmiş katkı 2610.
    with SqliteUnitOfWork(site.conf("real").db_path) as uow:
        point = PricePoint("XHT", date(2026, 11, 25), Decimal(9), "tefas")
        uow.prices.upsert(point, fetched_at=NOW)

    page = site.browser().get("/gercek/").text

    assert "Değer, enflasyona göre güncellenmiş yatırımın 113,00 TL altında: reel kayıp." in page


def test_weeks_without_published_cpi_use_the_last_period_and_say_so(site: Site) -> None:
    site.clock.current = datetime(2026, 12, 7, 9, 30, tzinfo=UTC)

    page = site.browser().get("/gercek/getiri").text

    assert 'aria-labelledby="getiri-deger-baslik getiri-deger-aciklama"' in page
    assert "son açıklanan dönem, Ekim 2026, kullanıldı." in page
    assert '<td data-label="Güncellenmiş yatırım" class="num">2.610,00 TL *</td>' in page
    assert _weeks(page)[-1] == "7 Aralık"


def test_without_cpi_the_adjusted_line_is_missing_and_no_verdict_is_given(site: Site) -> None:
    with SqliteUnitOfWork(site.conf("sanal").db_path, sanal=True) as uow:
        tx = Transaction("XHT", date(2026, 11, 25), Side.BUY, Decimal(90), Decimal(11))
        uow.transactions.add(tx, external_ref=None, note=None, created_at=NOW)

    page = site.browser().get("/sanal/").text

    assert "TÜFE yok" in page
    assert "reel kazanç" not in page
    assert "reel kayıp" not in page
