"""Yürürlük tarihli ayarlar (K-127): o günün sürümü, sürüm kuralları, aya göre maaş günü."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finans.domain.models import YearMonth
from finans.domain.settings import (
    SettingVersion,
    check_version,
    effective_version,
    payday_schedule,
)

D = Decimal
TARGETS = {"hisse": D("0.6"), "dusuk_risk": D("0.4")}
CLASSES = frozenset(TARGETS)
START = SettingVersion(date.min, 15, D(1000), TARGETS)
TODAY = date(2026, 11, 25)


def _issues(new: SettingVersion, versions: list[SettingVersion] | None = None) -> list[str]:
    found = check_version(new, versions=versions or [START], classes=CLASSES, today=TODAY)
    return [f"{issue.path}: {issue.message}" for issue in found]


def test_the_version_in_force_is_the_last_one_started_by_that_day() -> None:
    january = replace(START, effective_from=date(2027, 1, 1), monthly_contribution=D(1200))
    corrected = replace(january, monthly_contribution=D(1300))

    assert effective_version([START, january], date(2026, 10, 31)) == START
    assert effective_version([START, january], date(2027, 1, 1)) == january
    assert effective_version([START, january, corrected], date(2027, 1, 5)) == corrected
    assert effective_version([], date(2027, 1, 1)) is None


def test_a_valid_change_from_today_has_no_issues() -> None:
    raised = replace(START, effective_from=TODAY, monthly_contribution=D(1200))

    assert _issues(raised) == []


@pytest.mark.parametrize(
    ("change", "issue"),
    [
        (
            {"effective_from": date(2026, 11, 24)},
            "effective_from: yürürlük günü en erken bugün (2026-11-25) olabilir.",
        ),
        (
            {"targets": {"hisse": D("0.6"), "dusuk_risk": D("0.3")}},
            "targets: hedeflerin toplamı tam 1 olmalı, şu an 0.9.",
        ),
        (
            {"targets": {"hisse": D("1.1"), "dusuk_risk": D("-0.1")}},
            "targets.dusuk_risk: 0 ile 1 arasında olmalı; -0.1 verildi.",
        ),
        (
            {"targets": {"hisse": D(1)}},
            "targets: sınıflar portfolio.toml'dakiyle aynı olmalı; eksik: dusuk_risk.",
        ),
        (
            {"monthly_contribution": D(-1)},
            "monthly_contribution: negatif olamaz; -1 verildi.",
        ),
        (
            {"payday": 32},
            "payday: 1 ile 31 arasında olmalı; 32 verildi.",
        ),
    ],
)
def test_a_broken_version_is_refused_with_the_reason(change: dict[str, object], issue: str) -> None:
    new = replace(START, **{"effective_from": TODAY, **change})  # type: ignore[arg-type]

    assert issue in _issues(new)


def test_a_payday_change_starts_only_on_the_first_of_a_month() -> None:
    mid_month = replace(START, effective_from=date(2026, 12, 10), payday=20)
    first = replace(START, effective_from=date(2027, 1, 1), payday=20)
    same_day_mid_month = replace(
        START, effective_from=date(2026, 12, 10), monthly_contribution=D(1200)
    )

    assert _issues(mid_month) == [
        "effective_from: maaş günü değişikliği yalnız bir ayın 1'inden geçerli olabilir."
    ]
    assert _issues(first) == []
    assert _issues(same_day_mid_month) == []


def test_each_month_takes_its_payday_from_the_version_on_its_first_day() -> None:
    moved = replace(START, effective_from=date(2027, 1, 1), payday=20)
    schedule = payday_schedule([START, moved], fallback=None)

    assert schedule(YearMonth(2026, 12)) == 15
    assert schedule(YearMonth(2027, 1)) == 20
    assert payday_schedule([], fallback=10)(YearMonth(2027, 1)) == 10
