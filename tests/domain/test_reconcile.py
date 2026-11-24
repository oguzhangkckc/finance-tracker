from datetime import date
from decimal import Decimal

from finans.domain.models import PricePoint, Side, Transaction
from finans.domain.reconcile import (
    EvidenceBasis,
    Finding,
    PriceDateEvidence,
    StatementLine,
    reconcile,
)

D = Decimal
DAY = date(2026, 11, 23)
XHT_PRICES = {
    date(2026, 11, 17): "1.7",
    date(2026, 11, 18): "1.71",
    date(2026, 11, 19): "1.72",
    date(2026, 11, 20): "1.744322",
    date(2026, 11, 23): "1.73",
    date(2026, 11, 24): "1.715559",
}
PRICES = [PricePoint("XHT", d, D(p), "tefas") for d, p in XHT_PRICES.items()] + [
    PricePoint("XPP", d, D(7), "tefas") for d in XHT_PRICES
]
DAYS = tuple(sorted(XHT_PRICES))
TRADES = [
    ("#1", Transaction("XHT", date(2026, 11, 17), Side.BUY, D(10), D("1.7"))),
    ("#2", Transaction("XHT", date(2026, 11, 20), Side.BUY, D(5), D("1.744322"))),
    ("#3", Transaction("XPP", date(2026, 11, 18), Side.BUY, D(100), D(7))),
    ("#4", Transaction("XAL", date(2026, 11, 18), Side.BUY, D(3), D(12))),
]
UNITS_HINT = "eksik ya da yanlış işlem olabilir"


def _line(units: str, value: str, price: str | None = None, code: str = "XHT") -> StatementLine:
    return StatementLine(2, DAY, code, D(units), None if price is None else D(price), D(value))


def _only(line: StatementLine) -> tuple[Finding, str]:
    report = reconcile([line], TRADES, PRICES, DAYS)
    item = next(i for i in report.items if i.code == line.code)
    return item.finding, item.message


def test_matching_lines_pass_and_record_same_day_price_evidence() -> None:
    lines = [_line("15", "25.95", "1.73"), _line("100", "700", code="XPP")]

    report = reconcile(lines, TRADES[:3], PRICES, DAYS)

    assert [(i.code, i.finding) for i in report.items] == [
        ("XHT", Finding.MATCH),
        ("XPP", Finding.MATCH),
    ]
    assert report.passed
    assert report.evidence == (
        PriceDateEvidence("XHT", DAY, DAY, 0, EvidenceBasis.PRICE_AND_VALUE),
        PriceDateEvidence("XPP", DAY, DAY, 0, EvidenceBasis.VALUE),
    )


def test_units_difference_points_at_a_missing_or_wrong_trade() -> None:
    assert _only(_line("14", "24.22", "1.73")) == (
        Finding.UNITS,
        "adet farkı: ekstrede 14, kayıtlarda 15; eksik ya da yanlış işlem olabilir",
    )


def test_units_gap_equal_to_a_recent_buy_is_a_possible_value_date_difference() -> None:
    report = reconcile([_line("10", "17.30", "1.73")], TRADES[:2], PRICES, DAYS)
    [item] = report.items
    assert item.finding is Finding.UNITS
    assert item.message == (
        "adet farkı: ekstrede 10, kayıtlarda 15; olası valör farkı (işlem #2, 2026-11-20)"
    )
    assert not report.passed


def test_recent_sell_explains_a_statement_that_still_shows_the_units() -> None:
    sell = ("#5", Transaction("XHT", DAY, Side.SELL, D(4), D("1.73")))
    report = reconcile([_line("15", "25.95", "1.73")], [*TRADES[:2], sell], PRICES, DAYS)
    assert report.items[0].message == (
        "adet farkı: ekstrede 15, kayıtlarda 11; olası valör farkı (işlem #5, 2026-11-23)"
    )


def test_trade_before_the_last_five_trading_days_is_not_a_value_date_difference() -> None:
    line = StatementLine(2, date(2026, 11, 24), "XHT", D(5), None, D("8.58"))
    [item] = reconcile([line], TRADES[:2], PRICES, DAYS).items
    assert item.message == f"adet farkı: ekstrede 5, kayıtlarda 15; {UNITS_HINT}"


def test_statement_before_any_trading_day_has_no_value_date_hint() -> None:
    line = StatementLine(2, date(2026, 11, 13), "XHT", D(3), None, D("5.10"))
    [item] = reconcile([line], TRADES[:2], PRICES, DAYS).items
    assert item.message == f"adet farkı: ekstrede 3, kayıtlarda 0; {UNITS_HINT}"


def test_gap_in_the_wrong_direction_is_not_a_value_date_difference() -> None:
    [item] = reconcile([_line("20", "34.60", "1.73")], TRADES[:2], PRICES, DAYS).items
    assert item.message == f"adet farkı: ekstrede 20, kayıtlarda 15; {UNITS_HINT}"


def test_price_difference_names_the_day_whose_price_the_statement_used() -> None:
    report = reconcile([_line("15", "26.16", "1.744322")], TRADES[:2], PRICES, DAYS)
    [item] = report.items
    assert item.finding is Finding.PRICE
    assert item.message == (
        "fiyat farkı: ekstrede 1.744322, kayıtlarda 1.73 (2026-11-23); ekstre fiyatı "
        "2026-11-20 TEFAS fiyatıyla eşleşiyor (-1 işlem günü); değer de tutuyor"
    )
    assert report.evidence == (
        PriceDateEvidence("XHT", DAY, date(2026, 11, 20), -1, EvidenceBasis.PRICE_AND_VALUE),
    )
    assert not report.passed


def test_coarse_statement_price_is_placed_by_its_value_not_called_rounding() -> None:
    report = reconcile([_line("15", "26.16", "1.74")], TRADES[:2], PRICES, DAYS)
    [item] = report.items
    assert item.finding is Finding.PRICE
    assert item.message == (
        "fiyat farkı: ekstrede 1.74, kayıtlarda 1.73 (2026-11-23); ekstre fiyatı "
        "2026-11-20 TEFAS fiyatıyla eşleşiyor (-1 işlem günü); değer de tutuyor"
    )
    assert report.evidence[0].basis is EvidenceBasis.PRICE_AND_VALUE


def test_price_match_whose_value_does_not_fit_is_weaker_evidence() -> None:
    report = reconcile([_line("15", "30", "1.744322")], TRADES[:2], PRICES, DAYS)
    [item] = report.items
    assert item.message.endswith(
        "2026-11-20 TEFAS fiyatıyla eşleşiyor (-1 işlem günü); değer bu fiyatla da tutmuyor"
    )
    assert report.evidence[0].basis is EvidenceBasis.PRICE


def test_without_a_price_the_value_reveals_the_price_day() -> None:
    report = reconcile([_line("15", "26.16")], TRADES[:2], PRICES, DAYS)
    [item] = report.items
    assert item.finding is Finding.PRICE
    assert item.message == (
        "fiyat farkı (değerden): ekstrede 26.16, kayıtlarda 25.95; değer 2026-11-20 TEFAS "
        "fiyatıyla tutuyor (-1 işlem günü)"
    )
    assert report.evidence[0].basis is EvidenceBasis.VALUE


def test_same_units_and_price_with_a_different_value_is_rounding() -> None:
    assert _only(_line("15", "25.97", "1.73")) == (
        Finding.ROUNDING,
        "yalnızca değer farkı: adet ve fiyat aynı, değer farkı 0.02 TL (yuvarlama)",
    )


def test_value_within_a_cent_matches() -> None:
    assert _only(_line("15", "25.96", "1.73"))[0] is Finding.MATCH


def test_value_without_any_matching_price_is_unexplained() -> None:
    assert _only(_line("15", "30")) == (
        Finding.UNEXPLAINED,
        "değer farkı 4.05 TL; ekstrede fiyat yok ve ±5 işlem gününde değeri tutan TEFAS "
        "fiyatı bulunamadı",
    )


def test_holding_without_a_price_cannot_be_checked() -> None:
    assert _only(_line("3", "36", code="XAL")) == (
        Finding.NO_PRICE,
        "kayıtlarda 2026-11-23 itibarıyla fiyat yok; `ft sync prices` çalıştır",
    )


def test_holdings_absent_from_the_statement_are_reported() -> None:
    report = reconcile([_line("15", "25.95", "1.73")], TRADES[:3], PRICES, DAYS)
    missing = [i for i in report.items if i.finding is Finding.MISSING]
    assert [(i.code, i.message) for i in missing] == [
        ("XPP", "kayıtlarda 100 adet var ama ekstrede yok"),
    ]
    assert not report.passed


def test_statement_on_a_weekend_is_compared_with_the_last_trading_day() -> None:
    saturday = date(2026, 11, 21)
    line = StatementLine(2, saturday, "XHT", D(15), D("1.744322"), D("26.16"))
    report = reconcile([line], TRADES[:2], PRICES, DAYS)
    assert [i.finding for i in report.items] == [Finding.MATCH]
    assert report.evidence == (
        PriceDateEvidence("XHT", saturday, date(2026, 11, 20), 0, EvidenceBasis.PRICE_AND_VALUE),
    )


def test_empty_statement_does_not_pass() -> None:
    assert not reconcile([], TRADES, PRICES, DAYS).passed


def test_stated_price_matching_no_nearby_day_is_still_a_price_difference() -> None:
    assert _only(_line("15", "37.5", "2.5")) == (
        Finding.PRICE,
        "fiyat farkı: ekstrede 2.5, kayıtlarda 1.73 (2026-11-23); ±5 işlem gününde eşleşen "
        "TEFAS fiyatı yok",
    )
