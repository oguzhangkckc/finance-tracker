from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from finans.adapters.clock import SystemClock
from finans.ports.clock import BUSINESS_TZ, Clock
from tests.fakes.clock import FixedClock


def test_system_clock_now_is_timezone_aware_utc() -> None:
    now = SystemClock().now()
    assert now.utcoffset() == timedelta(0)


def test_system_clock_today_is_istanbul_calendar_day() -> None:
    before = datetime.now(BUSINESS_TZ).date()
    today = SystemClock().today()
    after = datetime.now(BUSINESS_TZ).date()
    assert today in {before, after}


def test_istanbul_day_starts_three_hours_before_utc_day() -> None:
    clock = FixedClock(datetime(2026, 11, 23, 21, 30, tzinfo=UTC))
    assert clock.today() == date(2026, 11, 24)


def test_fixed_clock_returns_utc_even_if_given_another_offset() -> None:
    clock = FixedClock(datetime(2026, 11, 23, 15, 0, tzinfo=timezone(timedelta(hours=3))))
    assert clock.now() == datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    assert clock.now().utcoffset() == timedelta(0)


def test_fixed_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="saat dilimi"):
        FixedClock(datetime(2026, 11, 23, 12, 0))  # noqa: DTZ001


def test_fixed_clock_advance(clock: FixedClock) -> None:
    clock.advance(timedelta(hours=13))
    assert clock.today() == date(2026, 11, 24)


def test_both_clocks_satisfy_the_port() -> None:
    clocks: list[Clock] = [SystemClock(), FixedClock(datetime(2026, 1, 1, tzinfo=UTC))]
    assert all(c.now().tzinfo is not None for c in clocks)
