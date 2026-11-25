"""Yazma şifre kilidi: oturum başına 15 dakika, ortak sayaçla 5 yanlışta 15 dakika (K-126)."""

from datetime import UTC, datetime, timedelta

from finans.application.password import hash_password
from finans.web.lock import Attempt, LockState, WriteLock
from tests.fakes.clock import FixedClock

PASSWORD = "uzun bir parola cümlesi"  # noqa: S105 - sahte test değeri
STORED = hash_password(PASSWORD)
NOW = datetime(2026, 12, 15, 9, 0, tzinfo=UTC)


def _lock(stored: str | None = STORED) -> tuple[WriteLock, FixedClock]:
    clock = FixedClock(NOW)
    return WriteLock(stored, clock), clock


def test_the_right_password_opens_only_that_session_for_fifteen_minutes() -> None:
    lock, clock = _lock()

    assert lock.state("a") == LockState("locked")
    assert lock.try_unlock("a", PASSWORD) == Attempt("ok")
    assert lock.state("a") == LockState("open", minutes_left=15)
    assert lock.is_open("a")
    assert not lock.is_open("b")

    clock.advance(timedelta(minutes=14, seconds=1))
    assert lock.state("a") == LockState("open", minutes_left=1)
    clock.advance(timedelta(seconds=59))
    assert lock.state("a") == LockState("locked")


def test_wrong_passwords_count_down_and_the_fifth_locks_every_session() -> None:
    lock, clock = _lock()

    attempts = [lock.try_unlock(session, "yanlış bir parola") for session in "abcd"]
    assert [attempt.attempts_left for attempt in attempts] == [4, 3, 2, 1]
    assert {attempt.status for attempt in attempts} == {"wrong"}

    assert lock.lockout_until() is None
    until = NOW + timedelta(minutes=15)
    assert lock.try_unlock("e", "yanlış bir parola") == Attempt("locked", until=until)
    assert lock.try_unlock("f", PASSWORD) == Attempt("locked", until=until)
    assert lock.lockout_until() == until
    assert not lock.is_open("f")

    clock.advance(timedelta(minutes=15))
    assert lock.lockout_until() is None
    assert lock.try_unlock("f", PASSWORD) == Attempt("ok")


def test_the_lockout_starts_a_fresh_count_and_a_success_resets_it() -> None:
    lock, clock = _lock()
    for _ in range(4):
        lock.try_unlock("a", "yanlış bir parola")
    lock.try_unlock("a", PASSWORD)

    assert lock.try_unlock("a", "yanlış bir parola") == Attempt("wrong", attempts_left=4)

    for _ in range(4):
        lock.try_unlock("a", "yanlış bir parola")
    clock.advance(timedelta(minutes=15))
    assert lock.try_unlock("a", "yanlış bir parola") == Attempt("wrong", attempts_left=4)


def test_an_open_session_stays_open_through_a_lockout_caused_elsewhere() -> None:
    lock, _ = _lock()
    lock.try_unlock("benim", PASSWORD)

    for _ in range(5):
        lock.try_unlock("baskasi", "yanlış bir parola")

    assert lock.is_open("benim")


def test_without_a_stored_hash_writing_is_disabled() -> None:
    lock, _ = _lock(None)

    assert not lock.enabled
    assert lock.state("a") == LockState("disabled")
    assert lock.try_unlock("a", PASSWORD) == Attempt("disabled")
    assert not lock.is_open("a")
