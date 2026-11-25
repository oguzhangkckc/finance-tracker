from datetime import date
from decimal import Decimal

import pytest

from finans.domain.models import Instrument, InstrumentKind, PricePoint, Side, Transaction
from finans.domain.portfolio import QualityThresholds
from finans.domain.quality import (
    DataIssue,
    PriceFinding,
    check_prices,
    check_staleness,
    check_trade_prices,
    price_matches,
    trading_days,
)

D = Decimal
MM = Instrument("XPP", InstrumentKind.TEFAS_YAT, "dusuk_risk", category="para_piyasasi")
EQ = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse_tr")
GOLD = Instrument("XAL", InstrumentKind.TEFAS_YAT, "altin")
FOREIGN = Instrument("XHY", InstrumentKind.TEFAS_YAT, "hisse_yabanci")
ETF = Instrument("EOZ", InstrumentKind.TEFAS_BYF, "hisse_tr")
MANUAL = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")
# 11 ile 24 Kasım 2026 arasındaki iş günleri; 14, 15, 21 ve 22 hafta sonu.
WEEKDAYS = [date(2026, 11, d) for d in (11, 12, 13, 16, 17, 18, 19, 20, 23, 24)]
TODAY = date(2026, 11, 24)
SINCE = date(2026, 11, 1)


def _series(code: str, prices: dict[date, str]) -> list[PricePoint]:
    return [PricePoint(code, day, D(price), "tefas") for day, price in sorted(prices.items())]


def _flat(code: str, days: list[date], price: str = "10") -> list[PricePoint]:
    return _series(code, dict.fromkeys(days, price))


def _of(issues: list[DataIssue], check: str) -> list[tuple[str | None, date | None, str]]:
    return [(i.instrument, i.day, i.message) for i in issues if i.check == check]


@pytest.mark.parametrize(
    ("entered", "reference", "expected"),
    [
        ("0.1422", "0.142216", True),
        ("12.5123", "12.512345", True),
        ("12.5124", "12.512345", True),
        ("12.5122", "12.512345", False),
        ("12.5248", "12.512345", False),
        ("1.715559", "1.715559", True),
    ],
)
def test_entered_price_matches_within_one_unit_of_its_last_digit(
    entered: str, reference: str, expected: bool
) -> None:
    assert price_matches(D(entered), D(reference)) is expected


def test_trading_days_are_days_with_any_fund_price() -> None:
    prices = _flat("XHT", WEEKDAYS[:3]) + _flat("XPP", WEEKDAYS[2:4])
    assert trading_days(prices) == tuple(WEEKDAYS[:4])


def test_fund_is_stale_after_five_trading_days_without_a_price() -> None:
    history = {
        "XHT": _flat("XHT", WEEKDAYS),
        "XPP": _flat("XPP", WEEKDAYS[:5]),
        "XAL": _flat("XAL", WEEKDAYS[:6]),
    }

    issues = check_prices(
        [EQ, MM, GOLD, FOREIGN], history, today=TODAY, since=SINCE, thresholds=QualityThresholds()
    )

    assert _of(issues, "bayatlık") == [
        ("XPP", date(2026, 11, 17), "son fiyattan sonra 5 işlem günü fiyat yok"),
        ("XHY", None, "hiç fiyat yok; `ft sync prices` çalıştır"),
    ]


@pytest.mark.parametrize(
    ("today", "stale"), [(date(2026, 11, 24), True), (date(2026, 11, 23), False)]
)
def test_nothing_new_for_more_than_four_calendar_days_is_a_general_warning(
    today: date, stale: bool
) -> None:
    history = {"XHT": _flat("XHT", WEEKDAYS[:7])}

    issues = check_prices([EQ], history, today=today, since=SINCE, thresholds=QualityThresholds())

    expected = [(None, date(2026, 11, 19), "hiçbir fona 5 gündür yeni fiyat gelmedi")]
    assert _of(issues, "genel bayatlık") == (expected if stale else [])


def test_manual_price_older_than_fourteen_days_is_stale() -> None:
    def stale(last: date | None) -> bool:
        history = {} if last is None else {"ALTIN_GR": _flat("ALTIN_GR", [last], "3150")}
        issues = check_prices(
            [MANUAL], history, today=TODAY, since=SINCE, thresholds=QualityThresholds()
        )
        return bool(_of(issues, "bayatlık"))

    assert stale(date(2026, 11, 9))
    assert not stale(date(2026, 11, 10))
    assert stale(None)


def test_staleness_alone_leaves_out_jumps_and_gaps() -> None:
    history = {
        "XHT": _series("XHT", {WEEKDAYS[0]: "10", WEEKDAYS[2]: "20"}),
        "XPP": _flat("XPP", WEEKDAYS),
    }
    instruments = [EQ, MM, MANUAL]

    issues = check_staleness(instruments, history, today=TODAY)

    assert _of(issues, "bayatlık") == [
        ("XHT", date(2026, 11, 13), "son fiyattan sonra 7 işlem günü fiyat yok"),
        ("ALTIN_GR", None, "hiç fiyat girilmemiş; `ft price set` ile gir"),
    ]
    everything = check_prices(
        instruments, history, today=TODAY, since=SINCE, thresholds=QualityThresholds()
    )
    assert issues == [i for i in everything if i.check in {"bayatlık", "genel bayatlık"}]
    assert len(everything) > len(issues)


def test_jump_threshold_comes_from_category_then_class_then_default() -> None:
    thresholds = QualityThresholds.with_overrides({"hisse_tr": D("0.15"), "dusuk_risk": D("0.05")})
    assert thresholds.jump_for(EQ) == D("0.15")
    assert thresholds.jump_for(MM) == D("0.01")
    assert thresholds.jump_for(GOLD) == D("0.10")


def test_jumps_and_money_market_drops_inside_the_window_are_flagged() -> None:
    history = {
        "XHT": _series(
            "XHT",
            {
                date(2026, 10, 30): "50",
                date(2026, 11, 2): "100",
                date(2026, 11, 18): "100",
                date(2026, 11, 19): "116",
                date(2026, 11, 20): "116",
                date(2026, 11, 23): "133.4",
            },
        ),
        "XAL": _series("XAL", {date(2026, 11, 19): "10", date(2026, 11, 20): "11.1"}),
        "XPP": _series(
            "XPP",
            {date(2026, 11, 18): "7", date(2026, 11, 19): "7.08", date(2026, 11, 20): "7.07"},
        ),
    }
    thresholds = QualityThresholds.with_overrides({"hisse_tr": D("0.15")})

    issues = check_prices(
        [EQ, GOLD, MM], history, today=TODAY, since=date(2026, 11, 3), thresholds=thresholds
    )

    # XHT: 2.11'deki +%100 pencere dışında; 23.11'deki +%15 eşiği aşmıyor.
    assert _of(issues, "sıçrama") == [
        ("XHT", date(2026, 11, 19), "günlük değişim %16 (eşik %15; önceki 2026-11-18: 100)"),
        ("XAL", date(2026, 11, 20), "günlük değişim %11 (eşik %10; önceki 2026-11-19: 10)"),
        ("XPP", date(2026, 11, 19), "günlük değişim %1.14 (eşik %1; önceki 2026-11-18: 7)"),
    ]
    assert _of(issues, "monotonluk") == [
        ("XPP", date(2026, 11, 20), "para piyasası fonunun fiyatı düştü: 7.08 → 7.07"),
    ]


def test_missing_days_between_a_funds_first_and_last_price_are_gaps() -> None:
    history = {
        "XHT": _flat("XHT", WEEKDAYS),
        "XAL": _flat("XAL", [d for d in WEEKDAYS[2:8] if d != date(2026, 11, 17)]),
    }

    issues = check_prices(
        [EQ, GOLD], history, today=TODAY, since=SINCE, thresholds=QualityThresholds()
    )

    assert _of(issues, "boşluk") == [
        ("XAL", None, "1 işlem gününde fiyat yok (diğer fonlarda var): 2026-11-17"),
    ]


XHT_PRICES = {
    date(2026, 11, 17): "1.7",
    date(2026, 11, 18): "1.71",
    date(2026, 11, 19): "1.72",
    date(2026, 11, 20): "1.744322",
    date(2026, 11, 23): "1.73",
    date(2026, 11, 24): "1.715559",
}


def _tx(code: str, day: date, price: str, side: Side = Side.BUY) -> Transaction:
    return Transaction(code, day, side, D(10), D(price))


def _trade_issues(*trades: tuple[str, Transaction]) -> list[DataIssue]:
    history = {
        "XHT": _series("XHT", XHT_PRICES),
        "EOZ": _series("EOZ", {date(2026, 11, 23): "21.968691"}),
    }
    days = trading_days([p for series in history.values() for p in series])
    instruments = {i.code: i for i in (EQ, ETF, MANUAL)}
    return check_trade_prices(list(trades), instruments, history, days)


def test_matching_trade_prices_raise_nothing() -> None:
    assert (
        _trade_issues(
            ("#1", _tx("XHT", date(2026, 11, 20), "1.744322")),
            ("#2", _tx("EOZ", date(2026, 11, 23), "22.03")),
            ("#3", _tx("ALTIN_GR", date(2026, 11, 23), "3150")),
        )
        == []
    )


def test_mismatching_price_suggests_the_neighbouring_day_that_matches() -> None:
    [issue] = _trade_issues(("#4", _tx("XHT", date(2026, 11, 23), "1.7443")))
    assert str(issue) == (
        "[işlem fiyatı] XHT 2026-11-23 #4: fiyat 1.7443 o günün TEFAS fiyatıyla (1.73) uyuşmuyor "
        "(fark %0.83); 2026-11-20 gününün fiyatıyla (1.744322) eşleşiyor, "
        "tarih büyük olasılıkla 2026-11-20"
    )
    assert issue.level == "warn"


def test_trade_on_a_day_without_price_is_flagged_with_a_suggestion() -> None:
    [issue] = _trade_issues(("#5", _tx("XHT", date(2026, 11, 21), "1.715559", Side.SELL)))
    assert issue.message == (
        "işlem gününde TEFAS fiyatı yok (hafta sonu ya da tatil olabilir); "
        "2026-11-24 gününün fiyatıyla (1.715559) eşleşiyor, tarih büyük olasılıkla 2026-11-24"
    )


def test_short_prices_and_missing_data_are_only_noted() -> None:
    short, far = _trade_issues(
        ("#6", _tx("XHT", date(2026, 11, 24), "1.72")),
        ("#7", _tx("XHT", date(2026, 6, 1), "1.5")),
    )
    assert (short.level, short.message) == (
        "info",
        "fiyat 2 basamakla girilmiş; kontrol için en az 4 basamak gerekir",
    )
    assert (far.level, far.message) == (
        "info",
        "işlem günü çevresinde fiyat yok; kontrol edilemedi",
    )


def test_etf_price_is_compared_with_a_two_percent_tolerance() -> None:
    [issue] = _trade_issues(("#8", _tx("EOZ", date(2026, 11, 23), "22.5")))
    assert issue.message == "fiyat birim pay değerinden (21.968691) %2.42 farklı (eşik %2)"


def test_issue_without_a_location_prints_only_the_check_and_message() -> None:
    issue = DataIssue("genel bayatlık", "warn", None, None, "örnek")
    assert str(issue) == "[genel bayatlık] örnek"


def test_etf_without_a_price_on_the_trade_day_is_flagged() -> None:
    [issue] = _trade_issues(("#9", _tx("EOZ", date(2026, 11, 24), "22.03")))
    assert issue.message == "işlem gününde TEFAS fiyatı yok (hafta sonu ya da tatil olabilir)"


def test_mismatch_without_a_matching_neighbour_has_no_suggestion() -> None:
    [issue] = _trade_issues(("#10", _tx("XHT", date(2026, 11, 23), "1.9000")))
    assert issue.message == ("fiyat 1.9 o günün TEFAS fiyatıyla (1.73) uyuşmuyor (fark %9.83)")


def test_a_mismatch_carries_both_prices_the_difference_and_the_matching_day() -> None:
    """Web bunları kendi biçimiyle gösterir ve önerilen günü düzeltme düğmesine çevirir."""
    [issue] = _trade_issues(("#4", _tx("XHT", date(2026, 11, 23), "1.7443")))

    assert issue.price == PriceFinding(
        entered=D("1.7443"),
        published=D("1.73"),
        difference_percent=D("0.83"),
        suggested=date(2026, 11, 20),
        suggested_price=D("1.744322"),
    )
    assert issue.price.entered.as_tuple() == D("1.7443").as_tuple()


def test_a_day_without_a_price_carries_only_the_matching_day() -> None:
    [issue] = _trade_issues(("#5", _tx("XHT", date(2026, 11, 21), "1.715559", Side.SELL)))

    assert issue.price == PriceFinding(D("1.715559"), None, None, date(2026, 11, 24), D("1.715559"))


def test_a_mismatch_without_a_matching_neighbour_suggests_no_day() -> None:
    [issue] = _trade_issues(("#10", _tx("XHT", date(2026, 11, 23), "1.9000")))

    assert issue.price == PriceFinding(D("1.9000"), D("1.73"), D("9.83"))
    assert issue.price.entered.as_tuple() == D("1.9000").as_tuple()


def test_an_etf_difference_is_carried_without_a_suggestion() -> None:
    [issue] = _trade_issues(("#8", _tx("EOZ", date(2026, 11, 23), "22.5")))

    assert issue.price == PriceFinding(D("22.5"), D("21.968691"), D("2.42"))


def test_notes_without_a_comparison_carry_no_price_finding() -> None:
    short, far = _trade_issues(
        ("#6", _tx("XHT", date(2026, 11, 24), "1.72")),
        ("#7", _tx("XHT", date(2026, 6, 1), "1.5")),
    )

    assert (short.price, far.price) == (None, None)


def test_every_warning_carries_the_entered_price_even_without_a_published_one() -> None:
    [issue] = _trade_issues(("#9", _tx("EOZ", date(2026, 11, 24), "22.03")))

    assert issue.price == PriceFinding(D("22.03"), None, None)
