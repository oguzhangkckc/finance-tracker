from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.models import Instrument, InstrumentKind
from finans.ports.repositories import AlertEvent, AlertState, StoredRun

DAY = date(2026, 11, 24)
T1, T2, T3, T4 = (datetime(2026, 11, 24, 18, minute, tzinfo=UTC) for minute in (30, 31, 32, 33))


def test_each_attempt_is_a_row_and_ok_is_found_per_day(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        first = uow.runs.start("sync-prices", DAY, at=T1)
        uow.runs.finish(first, "partial", '{"eksik": ["XHT"]}', at=T2)
        assert not uow.runs.has_ok("sync-prices", DAY)
        second = uow.runs.start("sync-prices", DAY, at=T3)
        assert [run.id for run in uow.runs.running("sync-prices")] == [second]
        uow.runs.finish(second, "ok", "{}", at=T4)

        assert uow.runs.has_ok("sync-prices", DAY)
        assert uow.runs.running("sync-prices") == []
        assert [(run.id, run.status) for run in uow.runs.recent(since=T1)] == [
            (first, "partial"),
            (second, "ok"),
        ]
        assert uow.runs.last_ok("sync-prices") == StoredRun(
            second, "sync-prices", DAY, T3, T4, "ok", "{}"
        )
        assert uow.runs.last_ok("backup") is None


def test_alert_state_and_events_round_trip(migrated_db: Path) -> None:
    opened = AlertState("drift:hisse", "above", T1, None, None, '{"sapma": "0.07"}')
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.alerts.save(opened)
        event = uow.alerts.add_event(
            AlertEvent("drift:hisse", "opened", "above", Decimal("0.07"), T1)
        )
        assert uow.alerts.get("drift:hisse") == opened
        assert uow.alerts.list_open() == [opened]
        [pending] = uow.alerts.pending_events()
        assert (pending.id, pending.deviation, pending.notified_at) == (
            event,
            Decimal("0.07"),
            None,
        )

        uow.alerts.mark_notified([event], at=T2)
        resolved = replace(opened, direction=None, resolved_at=T3, last_notified_at=T2)
        uow.alerts.save(resolved)

        assert uow.alerts.pending_events() == []
        assert uow.alerts.list_open() == []
        assert uow.alerts.get("drift:hisse") == resolved
        assert uow.alerts.get("drift:altin") is None


def test_quiet_period_end_is_recorded_once(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        assert uow.allocation_state.quiet_ended_on() is None
        uow.allocation_state.end_quiet(date(2026, 12, 1))
        uow.allocation_state.end_quiet(date(2027, 1, 1))
        assert uow.allocation_state.quiet_ended_on() == date(2026, 12, 1)


def test_out_of_allocation_flag_round_trips_and_counts_as_a_change(migrated_db: Path) -> None:
    emergency = Instrument("ACL", InstrumentKind.TEFAS_YAT, "acil_durum", allocation=False)
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.instruments.sync([emergency])
        stored = uow.instruments.get("ACL")
        assert stored is not None
        assert stored.instrument == emergency
        assert uow.instruments.sync([replace(emergency, allocation=True)]).updated == ("ACL",)


def test_last_fetch_times_come_from_the_data(migrated_db: Path) -> None:
    from finans.domain.models import CpiPoint, PricePoint, YearMonth

    with SqliteUnitOfWork(migrated_db) as uow:
        assert uow.prices.last_fetched_at() is None
        assert uow.cpi.last_fetched_at("TP.TUKFIY2025.GENEL") is None
        uow.instruments.sync([Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse")])
        uow.prices.upsert(PricePoint("XHT", DAY, Decimal(1), "tefas"), fetched_at=T1)
        uow.prices.upsert(PricePoint("XHT", date(2026, 11, 25), Decimal(1), "tefas"), fetched_at=T3)
        uow.cpi.upsert(
            "TP.TUKFIY2025.GENEL",
            CpiPoint(YearMonth(2026, 10), Decimal(130)),
            base=None,
            fetched_at=T2,
        )
        assert uow.prices.last_fetched_at() == T3
        assert uow.cpi.last_fetched_at("TP.TUKFIY2025.GENEL") == T2
        assert uow.cpi.last_fetched_at("TP.FG.J0") is None
