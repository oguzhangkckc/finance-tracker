from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from finans.domain.models import DomainError, YearMonth
from finans.domain.numeric import is_exponent_notation


class InputError(ValueError):
    """Biçim hatası; kullanıcı arayüzü bunu kullanım hatası olarak gösterir (CLI'da çıkış 2)."""


def parse_amount(name: str, text: str, *, decimal: Literal[".", ","] = ".") -> Decimal:
    """Girilen basamak sayısı korunur; K-64 fiyat karşılaştırması buna dayanır.

    CLI'da ondalık ayırıcı nokta, web formunda virgüldür (K-126). Web'de nokta reddedilir:
    "5.000" binlik ayırıcıyla 5 TL olarak okunmasın.
    """
    if is_exponent_notation(text):
        plain = f"{Decimal(text.strip().replace(',', '.')):f}"
        shown = plain if decimal == "." else plain.replace(".", ",")
        raise InputError(f"{name}: üstel gösterim kullanılamaz; {text} yerine {shown} yaz.")
    if decimal == ",":
        if "." in text:
            raise InputError(
                f"{name}: nokta kullanılmaz; ondalık ayırıcı virgüldür (1,5), "
                "binlik ayırıcı yazılmaz (5000)."
            )
        plain = text.replace(",", ".") if text.count(",") == 1 else text
    elif text.count(",") == 1 and "." not in text:
        fixed = text.replace(",", ".")
        raise InputError(f"{name}: ondalık ayırıcı nokta olmalı; {text} yerine {fixed} yaz.")
    else:
        plain = text
    try:
        return Decimal(plain)
    except InvalidOperation:
        raise InputError(f"{name}: sayı olmalı, {text!r} verildi.") from None


def parse_day(text: str) -> date:
    try:
        value = date.fromisoformat(text)
    except ValueError:
        value = None
    if value is None or value.isoformat() != text:
        raise InputError(f"Tarih YYYY-AA-GG biçiminde olmalı, {text!r} verildi.")
    return value


def parse_period(text: str) -> YearMonth:
    try:
        return YearMonth.parse(text)
    except DomainError:
        message = f"Dönem YYYY-AA biçiminde geçerli bir ay olmalı, {text!r} verildi."
        raise InputError(message) from None
