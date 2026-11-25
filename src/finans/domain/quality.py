"""Veri kalitesi kontrolleri (DESIGN.md "Veri kalitesi kontrolleri", K-64, K-66)."""

from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from finans.domain.models import Instrument, InstrumentKind, PricePoint, Transaction
from finans.domain.numeric import canonical_text, in_domain_context
from finans.domain.portfolio import QualityThresholds

STALE_FUND_TRADING_DAYS = 5
STALE_ALL_DAYS = 4
STALE_MANUAL_DAYS = 14
NEIGHBOUR_TRADING_DAYS = 5
NO_DATA_WINDOW = timedelta(days=7)
MIN_CHECKED_DECIMALS = 4
ETF_TOLERANCE = Decimal("0.02")
_TEFAS = frozenset({InstrumentKind.TEFAS_YAT, InstrumentKind.TEFAS_EMK, InstrumentKind.TEFAS_BYF})
_NO_PRICE_ON_DAY = "işlem gününde TEFAS fiyatı yok (hafta sonu ya da tatil olabilir)"

Level = Literal["warn", "info"]
Series = Mapping[str, Sequence[PricePoint]]


@dataclass(frozen=True, slots=True)
class PriceFinding:
    """K-64 bulgusunun parçaları. Web bunları kendi biçimiyle gösterir ve önerilen günü
    düzeltme düğmesine çevirir; CLI `DataIssue.message`'ı yazar, çıktısı değişmez."""

    entered: Decimal
    published: Decimal | None
    difference_percent: Decimal | None
    suggested: date | None = None
    suggested_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DataIssue:
    check: str
    level: Level
    instrument: str | None
    day: date | None
    message: str
    ref: str | None = None
    price: PriceFinding | None = None

    def __str__(self) -> str:
        parts = [str(part) for part in (self.instrument, self.day, self.ref) if part is not None]
        where = " ".join(parts)
        if not where:
            return f"[{self.check}] {self.message}"
        return f"[{self.check}] {where}: {self.message}"


@in_domain_context
def price_matches(entered: Decimal, reference: Decimal) -> bool:
    """Girilen fiyat, son basamağında en çok 1 birim farkla eşleşir (yuvarlama ya da kesme)."""
    return abs(entered - reference) <= Decimal(1).scaleb(-_decimals(entered))


@in_domain_context
def trading_days(prices: Iterable[PricePoint]) -> tuple[date, ...]:
    return tuple(sorted({point.price_date for point in prices}))


@in_domain_context
def check_prices(
    instruments: Sequence[Instrument],
    history: Series,
    *,
    today: date,
    since: date,
    thresholds: QualityThresholds,
) -> list[DataIssue]:
    funds = [inst for inst in instruments if inst.kind in _TEFAS]
    days = trading_days(p for inst in funds for p in history.get(inst.code, ()))
    issues = check_staleness(instruments, history, today=today)
    for inst in funds:
        series = sorted(history.get(inst.code, ()), key=lambda p: p.price_date)
        issues.extend(_moves(inst, series, since, thresholds.jump_for(inst)))
    for inst in funds:
        issues.extend(_gaps(inst, history.get(inst.code, ()), days, since, today))
    return issues


@in_domain_context
def check_staleness(
    instruments: Sequence[Instrument], history: Series, *, today: date
) -> list[DataIssue]:
    funds = [inst for inst in instruments if inst.kind in _TEFAS]
    days = trading_days(p for inst in funds for p in history.get(inst.code, ()))
    issues: list[DataIssue] = []
    for inst in funds:
        issues.extend(_fund_staleness(inst, history.get(inst.code, ()), days))
    if funds and days and (today - days[-1]).days > STALE_ALL_DAYS:
        gap = (today - days[-1]).days
        message = f"hiçbir fona {gap} gündür yeni fiyat gelmedi"
        issues.append(DataIssue("genel bayatlık", "warn", None, days[-1], message))
    for inst in instruments:
        if inst.kind is InstrumentKind.MANUAL:
            issues.extend(_manual_staleness(inst, history.get(inst.code, ()), today))
    return issues


@in_domain_context
def check_trade_prices(
    trades: Sequence[tuple[str, Transaction]],
    instruments: Mapping[str, Instrument],
    history: Series,
    days: Sequence[date],
) -> list[DataIssue]:
    issues: list[DataIssue] = []
    for ref, tx in trades:
        inst = instruments.get(tx.instrument)
        if inst is None or inst.kind not in _TEFAS:
            continue
        prices = {p.price_date: p.price for p in history.get(tx.instrument, ())}
        finding = _trade_finding(inst, tx, prices, days)
        if finding is not None:
            message, level, price = finding
            issues.append(
                DataIssue("işlem fiyatı", level, tx.instrument, tx.trade_date, message, ref, price)
            )
    return issues


def _fund_staleness(
    inst: Instrument, series: Sequence[PricePoint], days: Sequence[date]
) -> list[DataIssue]:
    if not series:
        message = "hiç fiyat yok; `ft sync prices` çalıştır"
        return [DataIssue("bayatlık", "warn", inst.code, None, message)]
    last = max(p.price_date for p in series)
    missing = len(days) - bisect_left(days, last + timedelta(days=1))
    if missing < STALE_FUND_TRADING_DAYS:
        return []
    message = f"son fiyattan sonra {missing} işlem günü fiyat yok"
    return [DataIssue("bayatlık", "warn", inst.code, last, message)]


def _manual_staleness(
    inst: Instrument, series: Sequence[PricePoint], today: date
) -> list[DataIssue]:
    if not series:
        message = "hiç fiyat girilmemiş; `ft price set` ile gir"
        return [DataIssue("bayatlık", "warn", inst.code, None, message)]
    last = max(p.price_date for p in series)
    age = (today - last).days
    if age <= STALE_MANUAL_DAYS:
        return []
    return [DataIssue("bayatlık", "warn", inst.code, last, f"son elle giriş {age} gün önce")]


def _moves(
    inst: Instrument, series: Sequence[PricePoint], since: date, threshold: Decimal
) -> list[DataIssue]:
    issues: list[DataIssue] = []
    for previous, current in pairwise(series):
        if current.price_date < since:
            continue
        change = current.price / previous.price - 1
        if abs(change) > threshold:
            message = (
                f"günlük değişim %{canonical_text(_percent(change))} "
                f"(eşik %{canonical_text(_percent(threshold))}; "
                f"önceki {previous.price_date}: {canonical_text(previous.price)})"
            )
            issues.append(DataIssue("sıçrama", "warn", inst.code, current.price_date, message))
        if inst.category == "para_piyasasi" and current.price < previous.price:
            message = (
                "para piyasası fonunun fiyatı düştü: "
                f"{canonical_text(previous.price)} → {canonical_text(current.price)}"
            )
            issues.append(DataIssue("monotonluk", "warn", inst.code, current.price_date, message))
    return issues


def _gaps(
    inst: Instrument,
    series: Sequence[PricePoint],
    days: Sequence[date],
    since: date,
    today: date,
) -> list[DataIssue]:
    own = {p.price_date for p in series}
    if not own:
        return []
    first, last = min(own), max(own)
    missing = [d for d in days if first <= d <= last and since <= d <= today and d not in own]
    if not missing:
        return []
    listed = ", ".join(str(d) for d in missing)
    message = f"{len(missing)} işlem gününde fiyat yok (diğer fonlarda var): {listed}"
    return [DataIssue("boşluk", "warn", inst.code, None, message)]


def _trade_finding(
    inst: Instrument, tx: Transaction, prices: Mapping[date, Decimal], days: Sequence[date]
) -> tuple[str, Level, PriceFinding | None] | None:
    day, entered = tx.trade_date, tx.unit_price
    if not any(abs(d - day) <= NO_DATA_WINDOW for d in prices):
        return "işlem günü çevresinde fiyat yok; kontrol edilemedi", "info", None
    reference = prices.get(day)
    if inst.kind is InstrumentKind.TEFAS_BYF:
        # BYF borsadan alınır; birim pay değeriyle küçük fark olağandır ve tarih önerilmez.
        if reference is None:
            return _NO_PRICE_ON_DAY, "warn", PriceFinding(entered, None, None)
        difference = abs(entered / reference - 1)
        if difference <= ETF_TOLERANCE:
            return None
        percent = _percent(difference)
        message = (
            f"fiyat birim pay değerinden ({canonical_text(reference)}) %{canonical_text(percent)} "
            f"farklı (eşik %{canonical_text(_percent(ETF_TOLERANCE))})"
        )
        return message, "warn", PriceFinding(entered, reference, percent)
    digits = _decimals(entered)
    if reference is None:
        match = (
            _matching_day(entered, day, prices, days) if digits >= MIN_CHECKED_DECIMALS else None
        )
        return _NO_PRICE_ON_DAY + _hint(match), "warn", _finding(entered, None, None, match)
    if digits < MIN_CHECKED_DECIMALS:
        message = f"fiyat {digits} basamakla girilmiş; kontrol için en az 4 basamak gerekir"
        return message, "info", None
    if price_matches(entered, reference):
        return None
    percent = _percent(abs(entered / reference - 1))
    match = _matching_day(entered, day, prices, days)
    message = (
        f"fiyat {canonical_text(entered)} o günün TEFAS fiyatıyla ({canonical_text(reference)}) "
        f"uyuşmuyor (fark %{canonical_text(percent)})"
    )
    return message + _hint(match), "warn", _finding(entered, reference, percent, match)


def _finding(
    entered: Decimal,
    published: Decimal | None,
    percent: Decimal | None,
    match: tuple[date, Decimal] | None,
) -> PriceFinding:
    if match is None:
        return PriceFinding(entered, published, percent)
    return PriceFinding(entered, published, percent, *match)


def _matching_day(
    entered: Decimal, day: date, prices: Mapping[date, Decimal], days: Sequence[date]
) -> tuple[date, Decimal] | None:
    """Girilen fiyatla tutan en yakın komşu işlem günü (±5 işlem günü)."""
    index = bisect_left(days, day)
    window = days[max(0, index - NEIGHBOUR_TRADING_DAYS) : index + NEIGHBOUR_TRADING_DAYS + 1]
    candidates = [
        d for d in window if d != day and d in prices and price_matches(entered, prices[d])
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda d: (abs(d - day), d))
    return best, prices[best]


def _hint(match: tuple[date, Decimal] | None) -> str:
    if match is None:
        return ""
    best, price = match
    return (
        f"; {best} gününün fiyatıyla ({canonical_text(price)}) eşleşiyor, "
        f"tarih büyük olasılıkla {best}"
    )


def _decimals(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _percent(ratio: Decimal) -> Decimal:
    return (ratio * 100).quantize(Decimal("0.01"))
