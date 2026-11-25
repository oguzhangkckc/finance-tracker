"""Değer geçmişi ve aylık katkı (K-129); senaryo değerleri elle hesaplandı."""

from dataclasses import replace
from datetime import UTC, date, datetime
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
from finans.domain.settings import SettingVersion
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
        months = monthly_contributions(uow, scenario.CONFIG, end=date(2026, 11, 25), months=3)

    assert months == [
        MonthContribution(YearMonth(2026, 9), D(0), D(1000)),
        MonthContribution(YearMonth(2026, 10), D(0), D(1000)),
        MonthContribution(YearMonth(2026, 11), D(2610), D(1000)),
    ]


def test_each_month_plans_the_contribution_in_force_on_its_own_payday(migrated_db: Path) -> None:
    """K-127: Ekim'in maaş günü 15'inde 20 Ekim'deki artış henüz yok; Kasım'da maaş günü 25'e
    kaydı ve 20 Kasım'daki artış 25'inde yürürlükte."""
    scenario.seed(migrated_db)
    start = SettingVersion(date.min, 15, D(1000), scenario.CONFIG.targets)
    recorded = datetime(2026, 11, 25, 9, tzinfo=UTC)
    with SqliteUnitOfWork(migrated_db) as uow:
        for version in (
            start,
            replace(start, effective_from=date(2026, 10, 20), monthly_contribution=D(1100)),
            replace(
                start, effective_from=date(2026, 11, 1), payday=25, monthly_contribution=D(1100)
            ),
            replace(
                start, effective_from=date(2026, 11, 20), payday=25, monthly_contribution=D(1200)
            ),
        ):
            uow.settings.add(version, source="web", at=recorded)
        months = monthly_contributions(uow, scenario.CONFIG, end=date(2026, 11, 25), months=3)

    assert [(month.month, month.planned) for month in months] == [
        (YearMonth(2026, 9), D(1000)),
        (YearMonth(2026, 10), D(1000)),
        (YearMonth(2026, 11), D(1200)),
    ]


def test_without_a_payday_the_month_plans_from_its_first_day(migrated_db: Path) -> None:
    scenario.seed(migrated_db)
    start = SettingVersion(date.min, None, D(1000), scenario.CONFIG.targets)
    recorded = datetime(2026, 11, 25, 9, tzinfo=UTC)
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.settings.add(start, source="toml", at=recorded)
        raised = replace(start, effective_from=date(2026, 11, 1), monthly_contribution=D(1500))
        uow.settings.add(raised, source="web", at=recorded)
        months = monthly_contributions(uow, scenario.CONFIG, end=date(2026, 11, 25), months=2)

    assert [month.planned for month in months] == [D(1000), D(1500)]
