"""CSV ayrıştırıcılarının ortak alan kuralları; mesajlar satır numarasıyla birleştirilir."""

from datetime import date
from decimal import Decimal, InvalidOperation


class RowError(ValueError):
    pass


def parse_date(text: str) -> date:
    try:
        value = date.fromisoformat(text)
    except ValueError:
        value = None
    if value is None or value.isoformat() != text:
        raise RowError(f"date: YYYY-AA-GG olmalı, {text!r} verildi.")
    return value


def parse_decimal(name: str, text: str) -> Decimal:
    if text.count(",") == 1 and "." not in text:
        raise RowError(
            f"{name}: ondalık ayırıcı nokta olmalı; {text} yerine {text.replace(',', '.')} yaz."
        )
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise RowError(f"{name}: sayı olmalı, {text!r} verildi.") from None
    if not value.is_finite():
        raise RowError(f"{name}: sonlu bir sayı olmalı, {text!r} verildi.")
    return value
