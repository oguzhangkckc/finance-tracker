from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from finans.domain.models import Instrument, PricePoint, Transaction


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
