"""Aracı kurum ekstresiyle mutabakat (K-67)."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from finans.domain.models import ZERO, PricePoint, Transaction
from finans.domain.numeric import canonical_text, in_domain_context
from finans.domain.positions import build_positions
from finans.domain.quality import price_matches
from finans.domain.valuation import Holding, PriceHistory, value_book

VALUE_TOLERANCE = Decimal("0.01")
SEARCH_TRADING_DAYS = 5


@dataclass(frozen=True, slots=True)
class StatementLine:
    line: int
    day: date
    code: str
    units: Decimal
    price: Decimal | None
    value: Decimal


class Finding(StrEnum):
    MATCH = "uyumlu"
    UNITS = "adet farkı"
    PRICE = "fiyat farkı"
    ROUNDING = "yalnızca değer farkı"
    NO_PRICE = "fiyat yok"
    UNEXPLAINED = "açıklanamayan değer farkı"
    MISSING = "ekstrede yok"


class EvidenceBasis(StrEnum):
    PRICE_AND_VALUE = "fiyat ve değer"
    PRICE = "yalnızca fiyat"
    VALUE = "yalnızca değer"


@dataclass(frozen=True, slots=True)
class PriceDateEvidence:
    """Ekstrenin kullandığı fiyatın günü; offset, ekstre gününün son işlem gününe göre."""

    code: str
    statement_day: date
    price_day: date
    offset: int
    basis: EvidenceBasis


@dataclass(frozen=True, slots=True)
class ReconcileItem:
    finding: Finding
    code: str
    day: date
    message: str
    line: int | None = None
    value_difference: Decimal | None = None
    evidence: PriceDateEvidence | None = None

    @property
    def ok(self) -> bool:
        return self.finding is Finding.MATCH


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    items: tuple[ReconcileItem, ...]

    @property
    def passed(self) -> bool:
        return bool(self.items) and all(item.ok for item in self.items)

    @property
    def evidence(self) -> tuple[PriceDateEvidence, ...]:
        return tuple(item.evidence for item in self.items if item.evidence is not None)


@dataclass(frozen=True, slots=True)
class _Market:
    history: PriceHistory
    prices: Mapping[str, Mapping[date, Decimal]]
    days: Sequence[date]

    def anchor(self, day: date) -> int:
        return bisect_right(self.days, day) - 1

    def offset(self, statement_day: date, price_day: date) -> int:
        return bisect_left(self.days, price_day) - self.anchor(statement_day)

    def search(
        self, code: str, statement_day: date, accept: Callable[[Decimal], bool]
    ) -> date | None:
        anchor = self.anchor(statement_day)
        low, high = max(0, anchor - SEARCH_TRADING_DAYS), anchor + SEARCH_TRADING_DAYS + 1
        prices = self.prices.get(code, {})
        candidates = [d for d in self.days[low:high] if d in prices and accept(prices[d])]
        if not candidates:
            return None

        def distance(day: date) -> tuple[int, int]:
            offset = self.offset(statement_day, day)
            return abs(offset), offset

        return min(candidates, key=distance)


@in_domain_context
def reconcile(
    lines: Sequence[StatementLine],
    transactions: Sequence[Transaction],
    prices: Iterable[PricePoint],
    days: Sequence[date],
) -> ReconcileReport:
    points = list(prices)
    by_code: dict[str, dict[date, Decimal]] = defaultdict(dict)
    for point in points:
        by_code[point.instrument][point.price_date] = point.price
    market = _Market(PriceHistory(points), by_code, days)
    items: list[ReconcileItem] = []
    for day in sorted({line.day for line in lines}):
        valuation = value_book(build_positions(transactions, as_of=day), market.history, day)
        holdings = {holding.instrument: holding for holding in valuation.holdings}
        day_lines = [line for line in lines if line.day == day]
        items.extend(_check(line, holdings.get(line.code), market) for line in day_lines)
        listed = {line.code for line in day_lines}
        items.extend(
            ReconcileItem(
                Finding.MISSING,
                holding.instrument,
                day,
                f"kayıtlarda {canonical_text(holding.units)} adet var ama ekstrede yok",
            )
            for holding in valuation.holdings
            if holding.instrument not in listed and holding.units > ZERO
        )
    return ReconcileReport(tuple(items))


def _check(line: StatementLine, holding: Holding | None, market: _Market) -> ReconcileItem:
    def item(
        finding: Finding,
        message: str,
        difference: Decimal | None = None,
        evidence: PriceDateEvidence | None = None,
    ) -> ReconcileItem:
        return ReconcileItem(finding, line.code, line.day, message, line.line, difference, evidence)

    units = holding.units if holding is not None else ZERO
    if units != line.units:
        return item(
            Finding.UNITS,
            f"adet farkı: ekstrede {canonical_text(line.units)}, kayıtlarda "
            f"{canonical_text(units)}; eksik ya da yanlış işlem olabilir",
        )
    ours = holding.price if holding is not None else market.history.as_of(line.code, line.day)
    if ours is None:
        return item(
            Finding.NO_PRICE,
            f"kayıtlarda {line.day} itibarıyla fiyat yok; `ft sync prices` çalıştır",
        )
    our_value = units * ours.price
    difference = line.value - our_value

    def value_fits(price: Decimal) -> bool:
        return abs(units * price - line.value) <= VALUE_TOLERANCE

    stated = line.price
    if stated is None:
        if value_fits(ours.price):
            evidence = _evidence(line, ours.price_date, market, EvidenceBasis.VALUE)
            message = f"uyumlu (değer farkı {canonical_text(difference)} TL)"
            return item(Finding.MATCH, message, difference, evidence)
        found = market.search(line.code, line.day, value_fits)
        if found is None:
            message = (
                f"değer farkı {canonical_text(difference)} TL; ekstrede fiyat yok ve "
                f"±{SEARCH_TRADING_DAYS} işlem gününde değeri tutan TEFAS fiyatı bulunamadı"
            )
            return item(Finding.UNEXPLAINED, message, difference)
        evidence = _evidence(line, found, market, EvidenceBasis.VALUE)
        message = (
            f"fiyat farkı (değerden): ekstrede {canonical_text(line.value)}, kayıtlarda "
            f"{canonical_text(our_value)}; değer {found} TEFAS fiyatıyla tutuyor "
            f"({evidence.offset:+d} işlem günü)"
        )
        return item(Finding.PRICE, message, difference, evidence)

    def price_fits(price: Decimal) -> bool:
        return price_matches(stated, price)

    def both_fit(price: Decimal) -> bool:
        return price_fits(price) and value_fits(price)

    found = market.search(line.code, line.day, both_fit)
    if price_fits(ours.price):
        if value_fits(ours.price):
            evidence = _evidence(line, ours.price_date, market, EvidenceBasis.PRICE_AND_VALUE)
            message = f"uyumlu (değer farkı {canonical_text(difference)} TL)"
            return item(Finding.MATCH, message, difference, evidence)
        # Az basamaklı ekstre fiyatı birden çok günle eşleşebilir; değeri de tutan gün yoksa
        # fark yuvarlamadır.
        if found is None:
            evidence = _evidence(line, ours.price_date, market, EvidenceBasis.PRICE)
            message = (
                "yalnızca değer farkı: adet ve fiyat aynı, değer farkı "
                f"{canonical_text(difference)} TL (yuvarlama)"
            )
            return item(Finding.ROUNDING, message, difference, evidence)
    elif found is None:
        found = market.search(line.code, line.day, price_fits)
    message = (
        f"fiyat farkı: ekstrede {canonical_text(stated)}, kayıtlarda "
        f"{canonical_text(ours.price)} ({ours.price_date}); "
    )
    if found is None:
        missing = f"±{SEARCH_TRADING_DAYS} işlem gününde eşleşen TEFAS fiyatı yok"
        return item(Finding.PRICE, message + missing, difference)
    value_too = value_fits(market.prices[line.code][found])
    basis = EvidenceBasis.PRICE_AND_VALUE if value_too else EvidenceBasis.PRICE
    evidence = _evidence(line, found, market, basis)
    message += (
        f"ekstre fiyatı {found} TEFAS fiyatıyla eşleşiyor ({evidence.offset:+d} işlem günü); "
        + ("değer de tutuyor" if value_too else "değer bu fiyatla da tutmuyor")
    )
    return item(Finding.PRICE, message, difference, evidence)


def _evidence(
    line: StatementLine, price_day: date, market: _Market, basis: EvidenceBasis
) -> PriceDateEvidence:
    offset = market.offset(line.day, price_day)
    return PriceDateEvidence(line.code, line.day, price_day, offset, basis)
