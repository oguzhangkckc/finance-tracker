from types import TracebackType
from typing import Protocol, Self

from finans.ports.repositories import InstrumentRepo, PriceRepo, TransactionRepo


class UnitOfWork(Protocol):
    """Blok hatasız biterse COMMIT, hata ile biterse ROLLBACK."""

    instruments: InstrumentRepo
    transactions: TransactionRepo
    prices: PriceRepo

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
