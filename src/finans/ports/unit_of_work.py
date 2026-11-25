from types import TracebackType
from typing import Protocol, Self

from finans.ports.repositories import (
    AlertRepo,
    AllocationStateRepo,
    CpiRepo,
    InstrumentRepo,
    PriceRepo,
    RawPayloadRepo,
    RunRepo,
    SettingRepo,
    SubmissionRepo,
    TransactionRepo,
)


class StorageBusyError(Exception):
    """Başka bir yazma işlemi veritabanını bekleme süresinden uzun tuttu; hiçbir şey yazılmadı."""


class UnitOfWork(Protocol):
    """Blok hatasız biterse COMMIT, hata ile biterse ROLLBACK."""

    instruments: InstrumentRepo
    transactions: TransactionRepo
    prices: PriceRepo
    cpi: CpiRepo
    raw_payloads: RawPayloadRepo
    runs: RunRepo
    alerts: AlertRepo
    allocation_state: AllocationStateRepo
    submissions: SubmissionRepo
    settings: SettingRepo

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
