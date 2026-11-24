from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from finans.domain.allocation import Direction, EventKind
from finans.domain.models import CpiPoint, Instrument, PricePoint, Transaction
from finans.ports.sources import RawPayload


@dataclass(frozen=True, slots=True)
class StoredInstrument:
    instrument: Instrument
    active: bool


@dataclass(frozen=True, slots=True)
class InstrumentSync:
    added: tuple[str, ...]
    updated: tuple[str, ...]
    deactivated: tuple[str, ...]
    reactivated: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredTransaction:
    id: int
    transaction: Transaction
    external_ref: str | None
    note: str | None
    created_at: datetime
    voided_at: datetime | None
    void_reason: str | None

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None


@dataclass(frozen=True, slots=True)
class PriceWrite:
    status: Literal["inserted", "unchanged", "revised"]
    previous: Decimal | None = None
    previous_source: str | None = None


@dataclass(frozen=True, slots=True)
class CpiWrite:
    status: Literal["inserted", "unchanged", "revised"]
    previous: Decimal | None = None


class InstrumentRepo(Protocol):
    def sync(self, instruments: Sequence[Instrument]) -> InstrumentSync: ...
    def get(self, code: str) -> StoredInstrument | None: ...
    def list(self, *, include_inactive: bool = False) -> list[StoredInstrument]: ...


class TransactionRepo(Protocol):
    def add(
        self, tx: Transaction, *, external_ref: str | None, note: str | None, created_at: datetime
    ) -> int: ...
    def get(self, txn_id: int) -> StoredTransaction | None: ...
    def list(
        self,
        *,
        include_voided: bool = False,
        until: date | None = None,
        instrument: str | None = None,
    ) -> list[StoredTransaction]: ...
    def void(self, txn_id: int, *, reason: str, at: datetime) -> None: ...


class PriceRepo(Protocol):
    def upsert(self, point: PricePoint, *, fetched_at: datetime) -> PriceWrite: ...
    def history(self, *, until: date) -> list[PricePoint]: ...
    def latest(self, instrument: str) -> PricePoint | None: ...
    def on(self, instrument: str, day: date) -> PricePoint | None: ...
    def last_fetched_at(self) -> datetime | None: ...


class CpiRepo(Protocol):
    def upsert(
        self, series: str, point: CpiPoint, *, base: str | None, fetched_at: datetime
    ) -> CpiWrite: ...
    def points(self, series: str) -> list[CpiPoint]: ...
    def latest(self, series: str) -> CpiPoint | None: ...
    def last_fetched_at(self, series: str) -> datetime | None: ...


class RawPayloadRepo(Protocol):
    def add(self, payload: RawPayload) -> int: ...


JobStatus = Literal["running", "ok", "partial", "failed"]


@dataclass(frozen=True, slots=True)
class StoredRun:
    id: int
    job: str
    logical_date: date
    started_at: datetime
    finished_at: datetime | None
    status: JobStatus
    detail: str | None


class RunRepo(Protocol):
    def start(self, job: str, logical_date: date, *, at: datetime) -> int: ...
    def finish(self, run_id: int, status: JobStatus, detail: str, *, at: datetime) -> None: ...
    def has_ok(self, job: str, logical_date: date) -> bool: ...
    def running(self, job: str) -> list[StoredRun]: ...
    def recent(self, *, since: datetime) -> list[StoredRun]: ...
    def last_ok(self, job: str) -> StoredRun | None: ...


@dataclass(frozen=True, slots=True)
class AlertState:
    """`direction` yalnızca alarm açıkken doludur."""

    fingerprint: str
    direction: Direction | None
    opened_at: datetime
    resolved_at: datetime | None
    last_notified_at: datetime | None
    payload: str


@dataclass(frozen=True, slots=True)
class AlertEvent:
    fingerprint: str
    kind: EventKind
    direction: Direction
    deviation: Decimal
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class StoredAlertEvent:
    id: int
    event: AlertEvent
    notified_at: datetime | None

    @property
    def deviation(self) -> Decimal:
        return self.event.deviation


class AlertRepo(Protocol):
    def get(self, fingerprint: str) -> AlertState | None: ...
    def list_open(self) -> list[AlertState]: ...
    def save(self, state: AlertState) -> None: ...
    def add_event(self, event: AlertEvent) -> int: ...
    def pending_events(self) -> list[StoredAlertEvent]: ...
    def mark_notified(self, event_ids: Sequence[int], *, at: datetime) -> None: ...


class AllocationStateRepo(Protocol):
    def quiet_ended_on(self) -> date | None: ...
    def end_quiet(self, day: date) -> None: ...
