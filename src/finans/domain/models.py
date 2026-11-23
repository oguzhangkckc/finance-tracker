import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from finans.domain.numeric import in_domain_context

_YEAR_MONTH = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})$")
ZERO = Decimal(0)


class DomainError(ValueError):
    pass


class OversellError(DomainError):
    pass


class InstrumentKind(StrEnum):
    TEFAS_YAT = "TEFAS_YAT"
    TEFAS_EMK = "TEFAS_EMK"
    TEFAS_BYF = "TEFAS_BYF"
    MANUAL = "MANUAL"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


def _require_finite(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise DomainError(f"{name} Decimal olmalı, {type(value).__name__} verildi")
    if not value.is_finite():
        raise DomainError(f"{name} sonlu bir sayı olmalı: {value}")
    return value


def _require_positive(name: str, value: object) -> None:
    if _require_finite(name, value) <= ZERO:
        raise DomainError(f"{name} sıfırdan büyük olmalı: {value}")


@dataclass(frozen=True, slots=True, order=True)
class YearMonth:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise DomainError(f"Geçersiz ay: {self.month}")

    @classmethod
    def of(cls, day: date) -> "YearMonth":
        return cls(day.year, day.month)

    @classmethod
    def parse(cls, text: str) -> "YearMonth":
        match = _YEAR_MONTH.match(text)
        if match is None:
            raise DomainError(f"Dönem YYYY-AA biçiminde olmalı: {text!r}")
        return cls(int(match["year"]), int(match["month"]))

    def shift(self, months: int) -> "YearMonth":
        index = self.year * 12 + (self.month - 1) + months
        return YearMonth(index // 12, index % 12 + 1)

    def previous(self) -> "YearMonth":
        return self.shift(-1)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True, slots=True)
class Instrument:
    code: str
    kind: InstrumentKind
    asset_class: str
    category: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise DomainError("Varlık kodu boş olamaz")


@dataclass(frozen=True, slots=True)
class CashFlow:
    on: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class Transaction:
    instrument: str
    trade_date: date
    side: Side
    units: Decimal
    unit_price: Decimal
    fee: Decimal = ZERO

    def __post_init__(self) -> None:
        _require_positive("units", self.units)
        _require_positive("unit_price", self.unit_price)
        if _require_finite("fee", self.fee) < ZERO:
            raise DomainError(f"fee negatif olamaz: {self.fee}")

    @in_domain_context
    def cash_flow(self) -> CashFlow:
        gross = self.units * self.unit_price
        if self.side is Side.BUY:
            return CashFlow(self.trade_date, -(gross + self.fee))
        return CashFlow(self.trade_date, gross - self.fee)


@dataclass(frozen=True, slots=True)
class PricePoint:
    instrument: str
    price_date: date
    price: Decimal
    source: str

    def __post_init__(self) -> None:
        try:
            _require_positive("price", self.price)
        except DomainError as exc:
            raise DomainError(
                f"Geçersiz fiyat ({self.instrument}, {self.price_date}): {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class CpiPoint:
    period: YearMonth
    index: Decimal

    def __post_init__(self) -> None:
        try:
            _require_positive("index", self.index)
        except DomainError as exc:
            raise DomainError(f"Geçersiz TÜFE endeksi ({self.period}): {exc}") from exc
