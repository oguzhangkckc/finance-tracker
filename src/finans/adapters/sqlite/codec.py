from datetime import UTC, datetime


def encode_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Zaman damgası saat dilimi bilgisi taşımalı")
    return value.astimezone(UTC).isoformat(timespec="seconds")
