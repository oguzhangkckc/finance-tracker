"""Yürürlük tarihli ayarlar (K-127): o günün sürümü, sürüm kuralları, aya göre maaş günü."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finans.domain.models import DomainError, YearMonth
from finans.domain.portfolio import AlertThresholds, PortfolioConfig
from finans.domain.settings import (
    ClassChanges,
    SettingVersion,
    changed_fields,
    check_version,
    class_changes,
    effective_version,
    overridden_on,
    payday_schedule,
    start_version,
    toml_differences,
    with_classes,
)

D = Decimal
TARGETS = {"hisse": D("0.6"), "dusuk_risk": D("0.4")}
CLASSES = frozenset(TARGETS)
START = SettingVersion(date.min, 15, D(1000), TARGETS)
TODAY = date(2026, 11, 25)
JANUARY = replace(START, effective_from=date(2027, 1, 1), monthly_contribution=D(1200))
TOML = PortfolioConfig((), TARGETS, D(1000), AlertThresholds(), payday=15)


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


def test_the_starting_version_takes_the_toml_values_from_the_first_day() -> None:
    assert start_version(TOML) == SettingVersion(date(1, 1, 1), 15, D(1000), TARGETS)


def test_a_new_class_joins_with_zero_weight_and_a_zero_weight_class_leaves() -> None:
    with_cash = replace(START, targets={**TARGETS, "nakit": D(0)})

    moved = with_classes(with_cash, {"hisse", "dusuk_risk", "altin"}, effective_from=TODAY)

    assert moved == replace(
        START,
        effective_from=TODAY,
        targets={"hisse": D("0.6"), "dusuk_risk": D("0.4"), "altin": D(0)},
    )


def test_a_class_with_weight_is_never_dropped_silently() -> None:
    with pytest.raises(DomainError, match="dusuk_risk"):
        with_classes(START, {"hisse"}, effective_from=TODAY)


def test_class_changes_cover_the_version_in_force_and_the_planned_ones() -> None:
    assert class_changes([START, JANUARY], CLASSES, today=TODAY) == ClassChanges((), (), (), ())

    changes = class_changes([START, JANUARY], {"hisse", "dusuk_risk", "altin"}, today=TODAY)

    assert changes == ClassChanges(("altin",), (), (), ())


def test_removing_a_class_with_weight_says_to_zero_it_first() -> None:
    zeroed = replace(START, effective_from=TODAY, targets={"hisse": D(1), "dusuk_risk": D(0)})
    planned = replace(JANUARY, targets=TARGETS)

    in_force = class_changes([START], {"hisse"}, today=TODAY)
    only_planned = class_changes([START, zeroed, planned], {"hisse"}, today=TODAY)
    free = class_changes([START, zeroed], {"hisse"}, today=TODAY)

    assert (in_force.removed, in_force.blocked) == (("dusuk_risk",), ("dusuk_risk",))
    assert [str(issue) for issue in in_force.issues] == [
        "targets.dusuk_risk: portfolio.toml'dan silinmiş ama geçerli ayardaki ağırlığı 0.4."
        " Önce ağırlığını 0 yap: sınıfı portfolio.toml'a geri ekle, `ft ayar hedef` ile 0 yap,"
        " sonra sil."
    ]
    assert [str(issue) for issue in only_planned.issues] == [
        "targets.dusuk_risk: portfolio.toml'dan silinmiş ama yürürlüğü 2027-01-01 olan planlanan"
        " sürümdeki ağırlığı 0.4. Önce ağırlığını 0 yap ya da o sürümden `ft ayar vazgec` ile"
        " vazgeç."
    ]
    assert free == ClassChanges((), ("dusuk_risk",), (), ())


def test_a_superseded_version_is_not_compared_with_the_toml() -> None:
    zeroed = replace(START, effective_from=TODAY, targets={"hisse": D(1), "dusuk_risk": D(0)})

    assert class_changes([START, zeroed], {"hisse"}, today=TODAY).issues == ()


def test_toml_values_that_differ_from_the_setting_are_named_without_values() -> None:
    other = PortfolioConfig(
        (), {"hisse": D("0.5"), "dusuk_risk": D("0.5")}, D(1200), AlertThresholds(), payday=20
    )
    same_amount = PortfolioConfig(
        (),
        {"hisse": D("0.60"), "dusuk_risk": D("0.40")},
        D("1000.00"),
        AlertThresholds(),
        payday=15,
    )

    assert toml_differences(START, TOML) == []
    assert toml_differences(START, same_amount) == []
    assert toml_differences(START, other) == ["maaş günü", "aylık katkı", "hedefler"]


def test_changed_fields_name_only_the_settings_that_differ() -> None:
    retargeted = replace(JANUARY, targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")})

    assert changed_fields(START, START) == ()
    assert (
        changed_fields(START, replace(START, targets={"dusuk_risk": D("0.40"), "hisse": D("0.60")}))
        == ()
    )
    assert changed_fields(START, JANUARY) == ("monthly_contribution",)
    assert changed_fields(START, retargeted) == ("monthly_contribution", "targets")


def test_a_later_version_carrying_another_value_overrides_the_change_from_its_day() -> None:
    february = replace(
        START, effective_from=date(2027, 2, 1), targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")}
    )
    march_old_targets = replace(
        START, effective_from=date(2027, 3, 1), monthly_contribution=D(1500)
    )
    march_new_targets = replace(february, effective_from=date(2027, 3, 1))

    assert overridden_on(february, [START, JANUARY, march_old_targets], ["targets"]) == (
        date(2027, 3, 1),
    )
    assert overridden_on(february, [START, JANUARY, march_new_targets], ["targets"]) == ()
    assert overridden_on(february, [START, march_old_targets], []) == ()
