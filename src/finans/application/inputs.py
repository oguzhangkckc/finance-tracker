from datetime import date
from decimal import Decimal, InvalidOperation

from finans.domain.models import DomainError, YearMonth


class InputError(ValueError):
    """Biçim hatası; kullanıcı arayüzü bunu kullanım hatası olarak gösterir (CLI'da çıkış 2)."""


def parse_amount(name: str, text: str) -> Decimal:
    """Girilen basamak sayısı korunur; K-64 fiyat karşılaştırması buna dayanır."""
    if text.count(",") == 1 and "." not in text:
        fixed = text.replace(",", ".")
        raise InputError(f"{name}: ondalık ayırıcı nokta olmalı; {text} yerine {fixed} yaz.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise InputError(f"{name}: sayı olmalı, {text!r} verildi.") from None
    if "e" in text.lower() and value.is_finite():
        raise InputError(f"{name}: üstel gösterim kullanılamaz; {text} yerine {value:f} yaz.")
    return value


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
