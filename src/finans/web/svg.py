"""Sunucuda üretilen SVG; koordinatlar Decimal'den, satır içi stil yok (K-128, K-129)."""

from decimal import Decimal
from typing import Final

from markupsafe import Markup

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
