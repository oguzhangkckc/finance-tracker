"""Sunucuda üretilen SVG grafikler (K-129): koordinatlar Decimal'den, çizgiler türüyle ayrılır."""

import re
from datetime import date
from decimal import Decimal

from finans.application.history import ValuePoint
from finans.web.svg import value_chart

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
