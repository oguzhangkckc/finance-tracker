from datetime import date
from decimal import Decimal
from typing import ClassVar

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finans.domain.inflation import (
    CpiSeries,
    annual_inflation,
    chain_link,
    deflator,
    fisher_real,
    reference_period,
)
from finans.domain.models import CpiPoint, DomainError, YearMonth
from tests.support.decimals import is_close

D = Decimal
DEC_2025 = YearMonth(2025, 12)


def _series(values: dict[str, str]) -> CpiSeries:
    return CpiSeries(CpiPoint(YearMonth.parse(p), D(v)) for p, v in values.items())


class TestCpiSeries:
    def test_empty_series_is_rejected(self) -> None:
        with pytest.raises(DomainError, match="boş"):
            CpiSeries([])

    def test_duplicate_period_is_rejected(self) -> None:
        points = [CpiPoint(DEC_2025, D(1)), CpiPoint(DEC_2025, D(2))]
        with pytest.raises(DomainError, match="2025-12"):
            CpiSeries(points)

    def test_bounds_and_lookup(self) -> None:
        series = _series({"2025-12": "105", "2025-10": "100"})
        assert series.earliest() == YearMonth(2025, 10)
        assert series.latest() == DEC_2025
        assert series.index(DEC_2025) == D(105)
        assert YearMonth(2025, 11) not in series

    def test_missing_period_names_the_period(self) -> None:
        with pytest.raises(DomainError, match="2025-11"):
            _series({"2025-10": "100"}).index(YearMonth(2025, 11))


class TestReferencePeriod:
    def test_previous_month_when_available(self) -> None:
        series = _series({"2025-09": "99", "2025-10": "100"})
        assert reference_period(date(2025, 11, 23), series) == YearMonth(2025, 10)

    def test_latest_available_before_release(self) -> None:
        series = _series({"2025-08": "98", "2025-09": "99"})
        assert reference_period(date(2025, 11, 2), series) == YearMonth(2025, 9)

    def test_january_refers_to_previous_december(self) -> None:
        series = _series({"2025-12": "105", "2026-01": "110"})
        assert reference_period(date(2026, 1, 15), series) == DEC_2025

    def test_date_before_series_is_rejected(self) -> None:
        with pytest.raises(DomainError, match="TÜFE"):
            reference_period(date(2025, 1, 15), _series({"2025-12": "105"}))


class TestChainLink:
    OLD: ClassVar[dict[str, str]] = {"2025-11": "200", "2025-12": "210"}
    NEW: ClassVar[dict[str, str]] = {"2025-12": "105", "2026-01": "110.25"}

    def test_old_series_is_rescaled_at_the_link_month(self) -> None:
        linked = chain_link(_series(self.OLD), _series(self.NEW), link=DEC_2025)
        assert linked.periods() == (YearMonth(2025, 11), DEC_2025, YearMonth(2026, 1))
        assert linked.index(YearMonth(2025, 11)) == D(100)
        assert linked.index(DEC_2025) == D(105)
        assert linked.index(YearMonth(2026, 1)) == D("110.25")

    def test_ratios_across_the_link_combine_both_series(self) -> None:
        linked = chain_link(_series(self.OLD), _series(self.NEW), link=DEC_2025)
        ratio = linked.index(YearMonth(2026, 1)) / linked.index(YearMonth(2025, 11))
        assert ratio == (D("110.25") / D(105)) * (D(210) / D(200))

    @pytest.mark.parametrize(
        ("old", "new"),
        [({"2025-11": "200"}, NEW), (OLD, {"2026-01": "110.25"})],
    )
    def test_link_month_must_exist_in_both_series(
        self, old: dict[str, str], new: dict[str, str]
    ) -> None:
        with pytest.raises(DomainError, match="2025-12"):
            chain_link(_series(old), _series(new), link=DEC_2025)

    @given(st.decimals(min_value=D("0.001"), max_value=D(1000), places=3))
    def test_rescaling_the_old_series_does_not_change_the_result(self, scale: Decimal) -> None:
        scaled_old = {period: str(D(value) * scale) for period, value in self.OLD.items()}
        reference = chain_link(_series(self.OLD), _series(self.NEW), link=DEC_2025)
        linked = chain_link(_series(scaled_old), _series(self.NEW), link=DEC_2025)
        for period in reference.periods():
            assert is_close(linked.index(period), reference.index(period), rel_tol=D("1e-24"))


class TestDeflator:
    SERIES: ClassVar[dict[str, str]] = {"2024-12": "100", "2025-12": "120"}

    def test_uses_reference_periods_of_both_dates(self) -> None:
        series = _series(self.SERIES)
        assert deflator(series, flow_date=date(2025, 1, 2), on=date(2026, 1, 2)) == D("1.2")

    def test_same_reference_month_gives_exactly_one(self) -> None:
        series = _series(self.SERIES)
        assert deflator(series, flow_date=date(2026, 1, 2), on=date(2026, 1, 20)) == D(1)


def test_annual_inflation_compares_with_same_month_previous_year() -> None:
    series = _series({"2024-12": "100", "2025-12": "130.65"})
    assert annual_inflation(series, DEC_2025) == D("0.3065")


def test_annual_inflation_requires_previous_year() -> None:
    with pytest.raises(DomainError, match="2024-12"):
        annual_inflation(_series({"2025-12": "130"}), DEC_2025)


def test_fisher_relation() -> None:
    assert is_close(fisher_real(D("0.5"), D("0.4")), D(1) / D(14))
    assert fisher_real(D("0.3"), D("0.2")) == D("1.3") / D("1.2") - 1


def test_fisher_is_below_naive_subtraction_under_positive_inflation() -> None:
    assert fisher_real(D("0.5"), D("0.4")) < D("0.5") - D("0.4")
