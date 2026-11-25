from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finans.domain.refresh import DAILY_REFRESH_LIMIT, RefreshDecision, refresh_decision

ISTANBUL = ZoneInfo("Europe/Istanbul")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ISTANBUL)


def test_a_weekday_with_no_recent_update_is_allowed() -> None:
    assert refresh_decision(_at(25, 10), accepted=[], last_sync=None) == RefreshDecision(True)


def test_an_hour_must_pass_since_the_last_request_or_sync() -> None:
    by_request = refresh_decision(_at(25, 10), accepted=[_at(25, 9, 30)], last_sync=None)
    by_sync = refresh_decision(_at(25, 12, 20), accepted=[], last_sync=_at(25, 12, 0))

    assert by_request == RefreshDecision(
        False, "son güncellemeden bu yana 1 saat geçmedi", _at(25, 10, 30)
    )
    assert by_sync.earliest == _at(25, 13, 0)
    assert refresh_decision(_at(25, 10, 30), accepted=[_at(25, 9, 30)], last_sync=None).allowed


def test_at_most_six_accepted_requests_per_istanbul_day() -> None:
    six = [_at(25, 3 + 2 * i) for i in range(DAILY_REFRESH_LIMIT)]

    decision = refresh_decision(_at(25, 18), accepted=six, last_sync=None)

    assert decision == RefreshDecision(False, "bugünkü 6 elle güncelleme kullanıldı", _at(26, 0))
    assert refresh_decision(_at(26, 0, 30), accepted=six, last_sync=None).allowed


def test_requests_of_the_previous_istanbul_day_do_not_count() -> None:
    # 24 Kasım 22:30 UTC İstanbul'da 25 Kasım 01:30'dur: bugüne sayılır; 20:00 UTC bir önceki gün.
    utc = ZoneInfo("UTC")
    today = datetime(2026, 11, 24, 22, 30, tzinfo=utc)
    yesterday = [datetime(2026, 11, 24, 20, 0, tzinfo=utc) - timedelta(minutes=i) for i in range(6)]

    assert refresh_decision(_at(25, 18), accepted=[*yesterday, today], last_sync=None).allowed


def test_weekends_are_closed_until_monday() -> None:
    saturday = refresh_decision(_at(28, 11), accepted=[], last_sync=None)
    sunday = refresh_decision(_at(29, 23), accepted=[], last_sync=None)

    assert saturday == RefreshDecision(False, "hafta sonu fiyat yayımlanmaz", _at(30, 0))
    assert sunday.earliest == _at(30, 0)


def test_the_daily_limit_on_friday_points_to_monday() -> None:
    friday = [_at(27, 3 + i) for i in range(DAILY_REFRESH_LIMIT)]

    assert refresh_decision(_at(27, 20), accepted=friday, last_sync=None).earliest == _at(30, 0)
