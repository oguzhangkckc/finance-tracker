"""Sunucuda üretilen SVG; koordinatlar Decimal'den, satır içi stil yok (K-128, K-129)."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from markupsafe import Markup, escape

from finans.application.history import MonthContribution, ValuePoint

_WIDTH: Final = Decimal(300)
_TENTH: Final = Decimal("0.1")


def _coordinate(value: Decimal) -> str:
    return str(value.quantize(_TENTH))


def allocation_bar(weight: Decimal, target: Decimal, *, alarm: bool = False) -> Markup:
    """Ağırlık çubuğu ve hedef çizgisi; anlamı yanındaki metin taşır, çubuk süs olarak gizlenir.
    Alarm eşiği aşılmışsa çubuk Kehribar olur (K-129); sapma yeşil ya da kırmızıyla gösterilmez."""
    filled = min(max(weight, Decimal(0)), Decimal(1)) * _WIDTH
    mark = max(min(max(target, Decimal(0)), Decimal(1)) * _WIDTH - 1, Decimal(0))
    return Markup(  # noqa: S704 - yalnız sayılardan kurulur
        '<svg class="alloc-bar" viewBox="0 0 300 14" preserveAspectRatio="none" aria-hidden="true">'
        '<rect class="track" x="0" y="3" width="300" height="8" rx="4"/>'
        f'<rect class="{"fill alarm" if alarm else "fill"}" x="0" y="3" '
        f'width="{_coordinate(filled)}" height="8" rx="4"/>'
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


_PLANNED_OFFSET: Final = Decimal("0.1")
_ACTUAL_OFFSET: Final = Decimal("0.52")
_BAR_SHARE: Final = Decimal("0.38")


def contribution_chart(
    months: Sequence[MonthContribution], *, chart_id: str, title: str, description: str
) -> Markup:
    """Ay başına planlanan (çerçeveli) ve gerçekleşen (dolu) katkı çubuğu; net satış yapılan ay
    sıfır çizgisinin altına iner. Sayılar altındaki tabloda da vardır."""
    values = [Decimal(0)] + [m.invested for m in months]
    values += [m.planned for m in months if m.planned is not None]
    low, high = min(values), max(values)
    if low == high:
        high = low + 1
    span = high - low
    high += span * _MARGIN
    if low < 0:
        low -= span * _MARGIN

    def y(value: Decimal) -> Decimal:
        return _BOTTOM - (value - low) / (high - low) * (_BOTTOM - _TOP)

    zero = y(Decimal(0))
    slot = _CHART_WIDTH / len(months)
    width = _coordinate(slot * _BAR_SHARE)
    bars: list[str] = []
    for index, month in enumerate(months):
        start = slot * index
        drawn = [("bar-actual", month.invested, _ACTUAL_OFFSET)]
        if month.planned is not None:
            drawn.insert(0, ("bar-planned", month.planned, _PLANNED_OFFSET))
        for name, value, offset in drawn:
            top, height = min(y(value), zero), abs(zero - y(value))
            bars.append(
                f'<rect class="{name}" x="{_coordinate(start + slot * offset)}" '
                f'y="{_coordinate(top)}" width="{width}" height="{_coordinate(height)}"/>'
            )
    return Markup(  # noqa: S704 - başlık ve açıklama escape edilir, geri kalanı sayı
        f'<svg class="chart-svg" viewBox="0 0 320 160" preserveAspectRatio="none" role="img" '
        f'aria-labelledby="{chart_id}-baslik {chart_id}-aciklama">'
        f'<title id="{chart_id}-baslik">{escape(title)}</title>'
        f'<desc id="{chart_id}-aciklama">{escape(description)}</desc>'
        f'<line class="baseline" x1="0" y1="{_coordinate(zero)}" x2="320" y2="{_coordinate(zero)}" '
        f'vector-effect="non-scaling-stroke"/>'
        f"{''.join(bars)}</svg>"
    )
