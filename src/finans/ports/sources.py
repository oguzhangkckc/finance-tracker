from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from finans.domain.models import CpiPoint, Instrument, PricePoint, Transaction, YearMonth
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


@dataclass(frozen=True, slots=True)
class RawPayload:
    """Kaynaktan gelen ham yanıt; hata ayıklama için saklanır. request_key sır içermez."""

    source: str
    request_key: str
    fetched_at: datetime
    body: bytes


class SourceError(Exception):
    """Dış kaynaktan veri alınamadı; mesaj sır içermez."""


class SourceBlocked(SourceError):
    """Kaynak isteği reddetti ya da sınırladı; aynı kaynağa başka istek atılmaz (K-71)."""


@dataclass(frozen=True, slots=True)
class FetchResult[T]:
    points: list[T]
    raw: list[RawPayload]


class CpiSource(Protocol):
    def fetch(self, series: str, start: YearMonth, end: YearMonth) -> FetchResult[CpiPoint]: ...


class PriceSource(Protocol):
    name: str

    def fetch(self, inst: Instrument, start: date, end: date) -> FetchResult[PricePoint]: ...
