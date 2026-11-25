"""Sunucuda üretilen SVG; koordinatlar Decimal'den, satır içi stil yok (K-128, K-129)."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from markupsafe import Markup, escape

from finans.application.history import ValuePoint

_WIDTH: Final = Decimal(300)
_TENTH: Final = Decimal("0.1")


def _coordinate(value: Decimal) -> str:
    return str(value.quantize(_TENTH))


def allocation_bar(weight: Decimal, target: Decimal) -> Markup:
    """Ağırlık çubuğu ve hedef çizgisi; anlamı yanındaki metin taşır, çubuk süs olarak gizlenir."""
    filled = min(max(weight, Decimal(0)), Decimal(1)) * _WIDTH
    mark = max(min(max(target, Decimal(0)), Decimal(1)) * _WIDTH - 1, Decimal(0))
    return Markup(  # noqa: S704 - yalnız sayılardan kurulur
        '<svg class="alloc-bar" viewBox="0 0 300 14" preserveAspectRatio="none" aria-hidden="true">'
        '<rect class="track" x="0" y="3" width="300" height="8" rx="4"/>'
        f'<rect class="fill" x="0" y="3" width="{_coordinate(filled)}" height="8" rx="4"/>'
        f'<rect class="target" x="{_coordinate(mark)}" y="0" width="2" height="14"/>'
        "</svg>"
    )


_CHART_WIDTH: Final = Decimal(320)
_TOP: Final = Decimal(8)
_BOTTOM: Final = Decimal(152)
_MARGIN: Final = Decimal("0.05")


class _Scale:
    """Değerleri dikey eksene yerleştirir; aralığa %5 pay eklenir, düz çizgi ortada durur."""

    def __init__(self, values: Sequence[Decimal]) -> None:
        low, high = min(values), max(values)
        if low == high:
            low, high = low - 1, high + 1
        margin = (high - low) * _MARGIN
        self._low, self._high = low - margin, high + margin

    def y(self, value: Decimal) -> str:
        return _coordinate(
            _TOP + (self._high - value) / (self._high - self._low) * (_BOTTOM - _TOP)
        )


def _xs(count: int) -> list[str]:
    if count == 1:
        return [_coordinate(_CHART_WIDTH / 2)]
    step = _CHART_WIDTH / (count - 1)
    return [_coordinate(step * index) for index in range(count)]


def _line(xs: Sequence[str], values: Sequence[Decimal | None], scale: _Scale) -> str:
    """Eksik değerde çizgi kesilir; boşluk yanlış bir değer çizmekten iyidir."""
    parts: list[str] = []
    drawing = False
    for x, value in zip(xs, values, strict=True):
        if value is None:
            drawing = False
            continue
        parts.append(f"{'L' if drawing else 'M'}{x} {scale.y(value)}")
        drawing = True
    return " ".join(parts)


def _steps(xs: Sequence[str], values: Sequence[Decimal], scale: _Scale) -> str:
    parts = [f"M{xs[0]} {scale.y(values[0])}"]
    for x, value in zip(xs[1:], values[1:], strict=True):
        parts.append(f"H{x} V{scale.y(value)}")
    return " ".join(parts)


def value_chart(
    points: Sequence[ValuePoint], *, chart_id: str, title: str, description: str
) -> Markup:
    """Değer dolu, yatırılan para kesikli basamak, enflasyona göre güncellenmiş yatırım noktalı
    çizgi; fark yalnız renge dayanmaz (K-129). Sayılar altındaki tabloda da vardır."""
    values = [p.value for p in points]
    invested = [p.invested for p in points]
    adjusted = [p.adjusted for p in points]
    known = [v for v in (*values, *invested, *adjusted) if v is not None]
    scale = _Scale(known)
    xs = _xs(len(points))
    last = next(
        ((x, v) for x, v in zip(reversed(xs), reversed(values), strict=True) if v is not None),
        None,
    )
    dot = (
        ""
        if last is None
        else f'<circle class="dot-value" cx="{last[0]}" cy="{scale.y(last[1])}" r="3"/>'
    )
    stroke = 'vector-effect="non-scaling-stroke"'
    return Markup(  # noqa: S704 - başlık ve açıklama escape edilir, geri kalanı sayı
        f'<svg class="chart-svg" viewBox="0 0 320 160" preserveAspectRatio="none" role="img" '
        f'aria-labelledby="{chart_id}-baslik {chart_id}-aciklama">'
        f'<title id="{chart_id}-baslik">{escape(title)}</title>'
        f'<desc id="{chart_id}-aciklama">{escape(description)}</desc>'
        f'<path class="line-invested" d="{_steps(xs, invested, scale)}" {stroke}/>'
        f'<path class="line-adjusted" d="{_line(xs, adjusted, scale)}" {stroke}/>'
        f'<path class="line-value" d="{_line(xs, values, scale)}" {stroke}/>'
        f"{dot}</svg>"
    )
