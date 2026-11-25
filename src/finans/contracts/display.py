"""Türkçe sayı biçimi; raporu gösteren her kanal (metin, Telegram, web) aynısını kullanır."""

from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal

from finans.domain.numeric import canonical_text

# str.upper "i"yi "I" yapar; Türkçede "İ" olmalı.
_TURKISH_UPPER = {"i": "İ", "ı": "I"}


def class_label(code: str, labels: Mapping[str, str]) -> str:
    """Sınıf adı `[sinif_adlari]`'dan; yoksa koddan türetilir (K-128)."""
    if code in labels:
        return labels[code]
    words = code.replace("_", " ")
    first = words[:1]
    return _TURKISH_UPPER.get(first, first.upper()) + words[1:]


def _digits(value: Decimal, places: int) -> tuple[str, str]:
    """Banker yuvarlaması; binlik ayırıcı nokta, ondalık ayırıcı virgül."""
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
    integer, _, fraction = f"{abs(rounded):f}".partition(".")
    text = f"{int(integer):,}".replace(",", ".") + (f",{fraction}" if places else "")
    sign = "-" if rounded < 0 else ("+" if rounded > 0 else "")
    return sign, text


def money(value: Decimal) -> str:
    sign, text = _digits(value, 2)
    return f"{'-' if sign == '-' else ''}{text} TL"


def percent(rate: Decimal, *, places: int = 2, signed: bool = False) -> str:
    sign, text = _digits(rate * 100, places)
    return f"{sign if signed or sign == '-' else ''}%{text}"


def points(deviation: Decimal) -> str:
    sign, text = _digits(deviation * 100, 1)
    return f"{sign}{text} puan"


def exact(value: Decimal) -> str:
    """Fiyat ve adet yuvarlanmadan, ondalık ayırıcı virgülle (ör. 12,83827)."""
    return canonical_text(value).replace(".", ",")
