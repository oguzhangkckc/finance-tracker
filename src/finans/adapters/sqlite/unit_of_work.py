from contextlib import ExitStack, closing
from pathlib import Path
from types import TracebackType
from typing import Self

from finans.adapters.sqlite.connection import connect, transaction
from finans.adapters.sqlite.repositories import (
    SqliteInstrumentRepo,
    SqlitePriceRepo,
    SqliteTransactionRepo,
)
from finans.ports.repositories import InstrumentRepo, PriceRepo, TransactionRepo


class SqliteUnitOfWork:
    instruments: InstrumentRepo
    transactions: TransactionRepo
    prices: PriceRepo

    def __init__(self, path: Path, *, readonly: bool = False) -> None:
        self._path = path
        self._readonly = readonly
        self._stack = ExitStack()

    def __enter__(self) -> Self:
        with ExitStack() as stack:
            conn = stack.enter_context(closing(connect(self._path, readonly=self._readonly)))
            stack.enter_context(transaction(conn, immediate=not self._readonly))
            self.instruments = SqliteInstrumentRepo(conn)
            self.transactions = SqliteTransactionRepo(conn)
            self.prices = SqlitePriceRepo(conn)
            self._stack = stack.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stack.__exit__(exc_type, exc, tb)
