"""Değer geçmişi ve aylık katkı (K-129); senaryo değerleri elle hesaplandı."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.history import (
    MonthContribution,
    ValuePoint,
    monthly_contributions,
    value_history,
)
from finans.domain.models import YearMonth
from tests.support import report_scenario as scenario

D = Decimal
OCTOBER = YearMonth(2026, 10)


def test_weekly_points_carry_value_contribution_and_its_inflation_adjusted_twin(
    migrated_db: Path,
) -> None:
    scenario.seed(migrated_db)

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        points = value_history(uow, end=date(2026, 11, 25), cpi_series=scenario.SERIES)

    # 2 Kasım: XHT 100 × 10 + XPP 50 × 20 + XAC 10 × 50 = 2500, katkı da 2500.
    # 25 Kasım: XHT 110 × 11 + XPP 50 × 20,1 + XAC 10 × 50,2 = 2717; katkı 2500 + 10 × 11 = 2610.
    # Alışların ve günlerin referans ayı Ekim 2026: oran 1, güncellenmiş katkı katkıya eşit.
    early = [
        ValuePoint(date(2026, 11, day), D(2500), D(2500), D(2500), OCTOBER, estimated=False)
        for day in (4, 11, 18)
    ]
    assert points == [
        *early,
        ValuePoint(date(2026, 11, 25), D(2717), D(2610), D(2610), OCTOBER, estimated=False),
    ]


def test_a_week_whose_cpi_is_not_out_uses_the_last_period_and_says_so(migrated_db: Path) -> None:
    scenario.seed(migrated_db)

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        points = value_history(uow, end=date(2026, 12, 7), cpi_series=scenario.SERIES)

    last = points[-1]
    assert (last.day, last.cpi_period, last.estimated) == (date(2026, 12, 7), OCTOBER, True)
    assert last.adjusted == D(2610)
    assert [p.day for p in points][:2] == [date(2026, 11, 2), date(2026, 11, 9)]


def test_a_missing_price_or_cpi_leaves_a_gap_instead_of_a_wrong_line(migrated_db: Path) -> None:
    scenario.seed(migrated_db, priced=("XHT", "XPP"))

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        unpriced = value_history(uow, end=date(2026, 11, 25), cpi_series=scenario.SERIES)
        no_cpi = value_history(uow, end=date(2026, 11, 25), cpi_series="TP.YOK")

    assert {p.value for p in unpriced} == {None}
    assert {(p.adjusted, p.cpi_period) for p in no_cpi} == {(None, None)}
    assert [p.invested for p in no_cpi] == [D(2500), D(2500), D(2500), D(2610)]


def test_no_transactions_means_no_points(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert value_history(uow, end=date(2026, 11, 25), cpi_series=scenario.SERIES) == []


def test_monthly_contributions_show_the_last_months_with_the_plan(migrated_db: Path) -> None:
    scenario.seed(migrated_db)

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        months = monthly_contributions(uow, end=date(2026, 11, 25), months=3, planned=D(1000))

    assert months == [
        MonthContribution(YearMonth(2026, 9), D(0), D(1000)),
        MonthContribution(YearMonth(2026, 10), D(0), D(1000)),
        MonthContribution(YearMonth(2026, 11), D(2610), D(1000)),
    ]
