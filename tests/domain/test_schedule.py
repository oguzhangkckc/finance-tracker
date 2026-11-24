from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from finans.domain.models import DomainError
from finans.domain.schedule import JOBS, logical_date, payday_on

ISTANBUL = ZoneInfo("Europe/Istanbul")


def _at(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ISTANBUL)


@pytest.mark.parametrize(
    ("job", "now", "expected"),
    [
        ("sync-prices", _at(2026, 11, 24, 21, 30), date(2026, 11, 24)),
        ("sync-prices", _at(2026, 11, 24, 21, 29), date(2026, 11, 23)),
        ("sync-prices", _at(2026, 11, 28, 12, 0), date(2026, 11, 27)),
        ("sync-prices", _at(2026, 11, 30, 8, 0), date(2026, 11, 27)),
        ("weekly-report", _at(2026, 11, 29, 20, 0), date(2026, 11, 29)),
        ("weekly-report", _at(2026, 11, 30, 7, 0), date(2026, 11, 29)),
        ("weekly-report", _at(2026, 11, 29, 19, 59), date(2026, 11, 22)),
        ("monthly-report", _at(2026, 12, 5, 11, 0), date(2026, 11, 30)),
        ("monthly-report", _at(2026, 12, 10, 23, 0), date(2026, 11, 30)),
        ("monthly-report", _at(2026, 12, 5, 10, 59), date(2026, 10, 31)),
        ("monthly-report", _at(2027, 1, 3, 9, 0), date(2026, 11, 30)),
        ("sync-cpi", _at(2026, 12, 3, 10, 30), date(2026, 11, 1)),
        ("sync-cpi", _at(2026, 12, 5, 12, 0), date(2026, 11, 1)),
        ("sync-cpi", _at(2026, 12, 3, 10, 29), date(2026, 10, 1)),
        ("sync-cpi", _at(2027, 1, 10, 0, 0), date(2026, 12, 1)),
        ("backup", _at(2026, 11, 24, 3, 0), date(2026, 11, 24)),
        ("backup", _at(2026, 11, 24, 2, 59), date(2026, 11, 23)),
    ],
)
def test_logical_date_is_the_day_of_the_last_scheduled_run(
    job: str, now: datetime, expected: date
) -> None:
    assert logical_date(job, now) == expected


@pytest.mark.parametrize(
    ("payday", "now", "expected"),
    [
        (15, _at(2026, 11, 15, 9, 0), date(2026, 11, 15)),
        (15, _at(2026, 11, 15, 8, 59), date(2026, 10, 15)),
        (31, _at(2027, 2, 28, 9, 0), date(2027, 2, 28)),
        (31, _at(2027, 3, 1, 0, 0), date(2027, 2, 28)),
    ],
)
def test_payday_logical_date_is_the_last_payday(payday: int, now: datetime, expected: date) -> None:
    assert logical_date("payday", now, payday=payday) == expected


def test_payday_is_clamped_to_the_end_of_the_month() -> None:
    assert payday_on(2027, 2, 31) == date(2027, 2, 28)
    assert payday_on(2028, 2, 30) == date(2028, 2, 29)
    assert payday_on(2026, 11, 15) == date(2026, 11, 15)


@pytest.mark.parametrize("payday", [0, 32])
def test_payday_outside_the_month_days_is_rejected(payday: int) -> None:
    with pytest.raises(DomainError, match="1 ile 31"):
        payday_on(2026, 11, payday)


def test_payday_job_needs_a_payday_and_unknown_jobs_are_rejected() -> None:
    with pytest.raises(DomainError, match="payday"):
        logical_date("payday", _at(2026, 11, 24, 12, 0))
    with pytest.raises(DomainError, match="tanınmayan iş"):
        logical_date("export-snapshot", _at(2026, 11, 24, 12, 0))


def test_job_names_are_the_scheduled_entry_points() -> None:
    assert JOBS == (
        "sync-prices",
        "sync-cpi",
        "weekly-report",
        "monthly-report",
        "payday",
        "backup",
    )


@pytest.mark.parametrize(
    ("payday", "year", "month", "expected"),
    [
        (29, 2027, 2, date(2027, 2, 28)),
        (30, 2027, 2, date(2027, 2, 28)),
        (31, 2027, 2, date(2027, 2, 28)),
        (29, 2028, 2, date(2028, 2, 29)),
        (30, 2028, 2, date(2028, 2, 29)),
        (31, 2027, 4, date(2027, 4, 30)),
        (30, 2027, 4, date(2027, 4, 30)),
        (31, 2027, 5, date(2027, 5, 31)),
    ],
)
def test_late_payday_moves_to_the_last_day_of_short_months(
    payday: int, year: int, month: int, expected: date
) -> None:
    assert payday_on(year, month, payday) == expected
    on_the_day = _at(expected.year, expected.month, expected.day, 9, 0)
    assert logical_date("payday", on_the_day, payday=payday) == expected
    day_before = _at(expected.year, expected.month, expected.day - 1, 23, 0)
    assert logical_date("payday", day_before, payday=payday) < date(year, month, 1)
