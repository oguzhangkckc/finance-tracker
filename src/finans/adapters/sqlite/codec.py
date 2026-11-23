from datetime import UTC, date, datetime
from decimal import MAX_PREC, Context, Decimal, InvalidOperation

# normalize() bağlam hassasiyetine yuvarlar; burada yalnızca sondaki sıfırlar atılmalı.
_EXACT = Context(prec=MAX_PREC)


def encode_decimal(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"Decimal sonlu olmalı: {value!r}")
    if value.is_zero():
        return "0"
    return format(value.normalize(_EXACT), "f")


def decode_decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Decimal değil: {text!r}") from None
    if not value.is_finite() or encode_decimal(value) != text:
        raise ValueError(f"Kanonik Decimal değil: {text!r}")
    return value


def encode_date(value: date) -> str:
    return value.isoformat()


def decode_date(text: str) -> date:
    message = f"Tarih YYYY-AA-GG biçiminde geçerli bir gün olmalı: {text!r}"
    try:
        value = date.fromisoformat(text)
    except ValueError:
        raise ValueError(message) from None
    if value.isoformat() != text:
        raise ValueError(message)
    return value


def encode_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Zaman damgası saat dilimi bilgisi taşımalı")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def decode_timestamp(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise ValueError(f"Zaman damgası saat dilimi bilgisi taşımalı: {text!r}")
    return value
