from contextlib import ExitStack, closing
from pathlib import Path
from types import TracebackType
from typing import Self

from finans.adapters.sqlite.connection import connect, transaction
from finans.adapters.sqlite.operations import (
    SqliteAlertRepo,
    SqliteAllocationStateRepo,
    SqliteRunRepo,
    SqliteSettingRepo,
    SqliteSubmissionRepo,
)
from finans.adapters.sqlite.repositories import (
    SqliteCpiRepo,
    SqliteInstrumentRepo,
    SqlitePriceRepo,
    SqliteRawPayloadRepo,
    SqliteTransactionRepo,
)
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


class SqliteUnitOfWork:
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

    def __init__(self, path: Path, *, readonly: bool = False, sanal: bool = False) -> None:
        self._path = path
        self._readonly = readonly
        self._sanal = sanal
        self._stack = ExitStack()

    def __enter__(self) -> Self:
        with ExitStack() as stack:
            conn = stack.enter_context(
                closing(connect(self._path, readonly=self._readonly, sanal=self._sanal))
            )
            stack.enter_context(transaction(conn, immediate=not self._readonly))
            self.instruments = SqliteInstrumentRepo(conn)
            self.transactions = SqliteTransactionRepo(conn)
            self.prices = SqlitePriceRepo(conn)
            self.cpi = SqliteCpiRepo(conn)
            self.raw_payloads = SqliteRawPayloadRepo(conn)
            self.runs = SqliteRunRepo(conn)
            self.alerts = SqliteAlertRepo(conn)
            self.allocation_state = SqliteAllocationStateRepo(conn)
            self.submissions = SqliteSubmissionRepo(conn)
            self.settings = SqliteSettingRepo(conn)
            self._stack = stack.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stack.__exit__(exc_type, exc, tb)
