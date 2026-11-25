"""İş kaydı, alarm durumu ve dağılım durumu repository'leri (M4, 0004)."""

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime
from typing import Final

from finans.adapters.sqlite.codec import (
    decode_date,
    decode_decimal,
    decode_timestamp,
    encode_date,
    encode_decimal,
    encode_timestamp,
)
from finans.domain.allocation import Direction, EventKind
from finans.ports.repositories import (
    AlertEvent,
    AlertState,
    JobStatus,
    StoredAlertEvent,
    StoredRun,
)

_STATUS: Final[dict[str, JobStatus]] = {
    "running": "running",
    "ok": "ok",
    "partial": "partial",
    "failed": "failed",
}
_DIRECTION: Final[dict[str, Direction]] = {"above": "above", "below": "below"}
_KIND: Final[dict[str, EventKind]] = {"opened": "opened", "resolved": "resolved"}
_RUN_SELECT = "SELECT id, job, logical_date, started_at, finished_at, status, detail FROM job_run"
_ALERT_SELECT = (
    "SELECT fingerprint, direction, opened_at, resolved_at, last_notified_at, payload FROM alert"
)


def _timestamp(text: str | None) -> datetime | None:
    return None if text is None else decode_timestamp(text)


def _run(row: tuple[int, str, str, str, str | None, str, str | None]) -> StoredRun:
    run_id, job, logical_date, started_at, finished_at, status, detail = row
    return StoredRun(
        run_id,
        job,
        decode_date(logical_date),
        decode_timestamp(started_at),
        _timestamp(finished_at),
        _STATUS[status],
        detail,
    )


class SqliteRunRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start(self, job: str, logical_date: date, *, at: datetime) -> int:
        cursor = self._conn.execute(
            "INSERT INTO job_run (job, logical_date, started_at, status)"
            " VALUES (?, ?, ?, 'running')",
            (job, encode_date(logical_date), encode_timestamp(at)),
        )
        return int(cursor.lastrowid or 0)

    def finish(self, run_id: int, status: JobStatus, detail: str, *, at: datetime) -> None:
        self._conn.execute(
            "UPDATE job_run SET status = ?, detail = ?, finished_at = ? WHERE id = ?",
            (status, detail, encode_timestamp(at), run_id),
        )

    def has_ok(self, job: str, logical_date: date) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM job_run WHERE job = ? AND logical_date = ? AND status = 'ok'",
            (job, encode_date(logical_date)),
        ).fetchone()
        return row is not None

    def running(self, job: str) -> list[StoredRun]:
        rows = self._conn.execute(
            _RUN_SELECT + " WHERE job = ? AND status = 'running' ORDER BY id", (job,)
        ).fetchall()
        return [_run(row) for row in rows]

    def recent(self, *, since: datetime) -> list[StoredRun]:
        rows = self._conn.execute(
            _RUN_SELECT + " WHERE started_at >= ? ORDER BY id", (encode_timestamp(since),)
        ).fetchall()
        return [_run(row) for row in rows]

    def last_ok(self, job: str) -> StoredRun | None:
        row = self._conn.execute(
            _RUN_SELECT + " WHERE job = ? AND status = 'ok' ORDER BY logical_date DESC, id DESC",
            (job,),
        ).fetchone()
        return None if row is None else _run(row)


def _alert(row: tuple[str, str | None, str, str | None, str | None, str]) -> AlertState:
    fingerprint, direction, opened_at, resolved_at, last_notified_at, payload = row
    return AlertState(
        fingerprint,
        None if direction is None else _DIRECTION[direction],
        decode_timestamp(opened_at),
        _timestamp(resolved_at),
        _timestamp(last_notified_at),
        payload,
    )


def _optional(value: datetime | None) -> str | None:
    return None if value is None else encode_timestamp(value)


class SqliteAlertRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, fingerprint: str) -> AlertState | None:
        row = self._conn.execute(
            _ALERT_SELECT + " WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return None if row is None else _alert(row)

    def list_open(self) -> list[AlertState]:
        rows = self._conn.execute(
            _ALERT_SELECT + " WHERE state = 'open' ORDER BY fingerprint"
        ).fetchall()
        return [_alert(row) for row in rows]

    def save(self, state: AlertState) -> None:
        self._conn.execute(
            "INSERT INTO alert (fingerprint, state, direction, opened_at, resolved_at,"
            " last_notified_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (fingerprint) DO UPDATE SET state = excluded.state,"
            " direction = excluded.direction, opened_at = excluded.opened_at,"
            " resolved_at = excluded.resolved_at,"
            " last_notified_at = excluded.last_notified_at, payload = excluded.payload",
            (
                state.fingerprint,
                "resolved" if state.direction is None else "open",
                state.direction,
                encode_timestamp(state.opened_at),
                _optional(state.resolved_at),
                _optional(state.last_notified_at),
                state.payload,
            ),
        )

    def add_event(self, event: AlertEvent) -> int:
        cursor = self._conn.execute(
            "INSERT INTO alert_event (fingerprint, kind, direction, deviation, occurred_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                event.fingerprint,
                event.kind,
                event.direction,
                encode_decimal(event.deviation),
                encode_timestamp(event.occurred_at),
            ),
        )
        return int(cursor.lastrowid or 0)

    def pending_events(self) -> list[StoredAlertEvent]:
        rows = self._conn.execute(
            "SELECT id, fingerprint, kind, direction, deviation, occurred_at FROM alert_event"
            " WHERE notified_at IS NULL ORDER BY id"
        ).fetchall()
        return [
            StoredAlertEvent(
                event_id,
                AlertEvent(
                    fingerprint,
                    _KIND[kind],
                    _DIRECTION[direction],
                    decode_decimal(deviation),
                    decode_timestamp(occurred_at),
                ),
                None,
            )
            for event_id, fingerprint, kind, direction, deviation, occurred_at in rows
        ]

    def mark_notified(self, event_ids: Sequence[int], *, at: datetime) -> None:
        self._conn.executemany(
            # İlk teslim zamanı korunur; işaretleme tekrar çalışsa da değişmez (K-131).
            "UPDATE alert_event SET notified_at = ? WHERE id = ? AND notified_at IS NULL",
            [(encode_timestamp(at), event_id) for event_id in event_ids],
        )


class SqliteAllocationStateRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def quiet_ended_on(self) -> date | None:
        row = self._conn.execute(
            "SELECT quiet_ended_on FROM allocation_state WHERE id = 1"
        ).fetchone()
        return None if row is None or row[0] is None else decode_date(row[0])

    def end_quiet(self, day: date) -> None:
        self._conn.execute(
            "INSERT INTO allocation_state (id, quiet_ended_on) VALUES (1, ?)"
            " ON CONFLICT (id) DO UPDATE SET quiet_ended_on = excluded.quiet_ended_on"
            " WHERE allocation_state.quiet_ended_on IS NULL",
            (encode_date(day),),
        )


class SqliteSubmissionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def used(self, nonce: str) -> str | None:
        row = self._conn.execute(
            "SELECT ref FROM web_submission WHERE nonce = ?", (nonce,)
        ).fetchone()
        return None if row is None else str(row[0])

    def record(self, nonce: str, *, ref: str, at: datetime) -> None:
        self._conn.execute(
            "INSERT INTO web_submission (nonce, ref, used_at) VALUES (?, ?, ?)",
            (nonce, ref, encode_timestamp(at)),
        )
