from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from finans.domain.models import Transaction
from finans.domain.portfolio import PortfolioConfig


@dataclass(frozen=True, slots=True)
class ImportRow:
    line: int
    transaction: Transaction
    ref: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class ImportIssue:
    line: int | None
    message: str

    def __str__(self) -> str:
        return self.message if self.line is None else f"satır {self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class ParsedTransactions:
    rows: tuple[ImportRow, ...]
    issues: tuple[ImportIssue, ...]


class TransactionFile(Protocol):
    def read(self, path: Path) -> ParsedTransactions: ...


class PortfolioConfigSource(Protocol):
    def load(self, path: Path) -> PortfolioConfig:
        """Geçersiz dosyada bütün sorunlarla birlikte ConfigError yükseltir."""
        ...
