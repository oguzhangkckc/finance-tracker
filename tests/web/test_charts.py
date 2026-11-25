"""Sunucuda üretilen SVG grafikler (K-129): koordinatlar Decimal'den, çizgiler türüyle ayrılır."""

import re
from datetime import date
from decimal import Decimal

from finans.application.history import MonthContribution, ValuePoint
from finans.domain.models import YearMonth
from finans.web.svg import contribution_chart, value_chart

D = Decimal


def _point(day: int, value: str | None, invested: str, adjusted: str | None) -> ValuePoint:
    return ValuePoint(
        date(2026, 11, day),
        None if value is None else D(value),
        D(invested),
        None if adjusted is None else D(adjusted),
        None,
        estimated=False,
    )


POINTS = [
    _point(4, "100", "100", "100"),
    _point(11, "110", "100", "102"),
    _point(18, None, "150", "153"),
]


def _path(svg: str, name: str) -> str:
    found = re.search(rf'<path class="{name}" d="([^"]+)"', svg)
    assert found is not None, svg
    return found.group(1)


def test_three_lines_from_decimal_coordinates_with_a_gap_for_a_missing_price() -> None:
    # Ölçek 97,35 ile 155,65 arası (değerler 100 ile 153, %5 pay);
    # y = 8 + (155,65 - v) / 58,3 × 144.
    svg = str(value_chart(POINTS, chart_id="deger", title="Değerin seyri", description="Açıklama"))

    assert _path(svg, "line-value") == "M0.0 145.5 L160.0 120.8"
    assert _path(svg, "line-invested") == "M0.0 145.5 H160.0 V145.5 H320.0 V22.0"
    assert _path(svg, "line-adjusted") == "M0.0 145.5 L160.0 140.5 L320.0 14.5"
    assert '<circle class="dot-value" cx="160.0" cy="120.8" r="3"/>' in svg


def test_the_chart_is_an_image_with_its_own_title_and_description() -> None:
    svg = str(
        value_chart(POINTS, chart_id="deger", title="Değerin <seyri>", description="Üç çizgi")
    )

    assert 'role="img" aria-labelledby="deger-baslik deger-aciklama"' in svg
    assert '<title id="deger-baslik">Değerin &lt;seyri&gt;</title>' in svg
    assert '<desc id="deger-aciklama">Üç çizgi</desc>' in svg
    assert "style=" not in svg


def test_a_single_point_or_a_flat_line_still_draws() -> None:
    single = str(value_chart(POINTS[:1], chart_id="tek", title="t", description="d"))
    flat = str(
        value_chart(
            [_point(4, "100", "100", "100"), _point(11, "100", "100", "100")],
            chart_id="duz",
            title="t",
            description="d",
        )
    )

    assert _path(single, "line-value") == "M160.0 80.0"
    assert '<circle class="dot-value" cx="160.0" cy="80.0" r="3"/>' in single
    assert _path(flat, "line-value") == "M0.0 80.0 L320.0 80.0"


def test_contribution_bars_show_the_plan_outlined_and_the_actual_filled() -> None:
    # Ölçek 0 ile 2740,5 arası (en büyük 2610, %5 pay); y = 152 - v / 2740,5 × 144.
    months = [
        MonthContribution(YearMonth(2026, 9), D(0), D(1000)),
        MonthContribution(YearMonth(2026, 10), D(500), D(1000)),
        MonthContribution(YearMonth(2026, 11), D(2610), D(1000)),
    ]

    svg = str(contribution_chart(months, chart_id="katki", title="Katkı", description="Aylık"))

    planned = re.findall(r'<rect class="bar-planned" ([^/]+)/>', svg)
    actual = re.findall(r'<rect class="bar-actual" ([^/]+)/>', svg)
    assert planned == [
        'x="10.7" y="99.5" width="40.5" height="52.5"',
        'x="117.3" y="99.5" width="40.5" height="52.5"',
        'x="224.0" y="99.5" width="40.5" height="52.5"',
    ]
    assert actual == [
        'x="55.5" y="152.0" width="40.5" height="0.0"',
        'x="162.1" y="125.7" width="40.5" height="26.3"',
        'x="268.8" y="14.9" width="40.5" height="137.1"',
    ]
    assert 'role="img" aria-labelledby="katki-baslik katki-aciklama"' in svg


def test_a_month_of_net_selling_goes_below_the_line_and_no_plan_means_no_outline() -> None:
    months = [
        MonthContribution(YearMonth(2026, 10), D(-500), None),
        MonthContribution(YearMonth(2026, 11), D(1500), None),
    ]

    svg = str(contribution_chart(months, chart_id="k", title="t", description="d"))

    assert "bar-planned" not in svg
    zero = re.search(r'<line class="baseline" x1="0" y1="([\d.]+)"', svg)
    first = re.search(r'<rect class="bar-actual" x="[\d.]+" y="([\d.]+)"', svg)
    assert zero is not None
    assert first is not None
    assert first.group(1) == zero.group(1)
