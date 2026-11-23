from datetime import UTC, datetime, timedelta, timezone

import pytest

from finans.adapters.sqlite.codec import encode_timestamp


def test_timestamp_is_stored_as_utc_iso_seconds() -> None:
    istanbul_evening = datetime(
        2026, 11, 23, 23, 30, 15, 123456, tzinfo=timezone(timedelta(hours=3))
    )
    assert encode_timestamp(istanbul_evening) == "2026-11-23T20:30:15+00:00"


def test_utc_timestamp_round_trips() -> None:
    value = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    assert datetime.fromisoformat(encode_timestamp(value)) == value


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="saat dilimi"):
        encode_timestamp(datetime(2026, 11, 23, 12, 0))  # noqa: DTZ001
