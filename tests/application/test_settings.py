"""Yürürlük tarihli ayarlar okuyucularda (K-127): rapor mantıksal gününün, maaş günü planı maaş
gününün, alarm değerlendirildiği günün sürümünü kullanır; sürüm yoksa portfolio.toml geçerlidir."""

from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.alerts import AlertEvaluation, evaluate_alerts
from finans.application.report import ReportKind, build_report, payday_plan
from finans.application.settings import (
    HistoryRow,
    add_version,
    cancel_version,
    payday_for,
    propose,
    setting_history,
)
from finans.contracts.report import PaydayPlan, Report
from finans.domain.models import CpiPoint, DomainError, YearMonth
from finans.domain.portfolio import ConfigError
from finans.domain.settings import SettingVersion
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario

D = Decimal
CONFIG = scenario.CONFIG
START = SettingVersion(date.min, CONFIG.payday, CONFIG.monthly_contribution, CONFIG.targets)
JANUARY = replace(START, effective_from=date(2027, 1, 1), monthly_contribution=D(1200))
RECORDED = datetime(2026, 11, 25, 11, 0, tzinfo=UTC)
TODAY = date(2026, 11, 25)


def _database(tmp_path: Path, name: str) -> Path:
    db = tmp_path / name / "finans.db"
    db.parent.mkdir()
    with closing(connect(db)) as conn:
        apply(conn, bundled(), clock=FixedClock(RECORDED))
    scenario.seed(db)
    # Aylık rapor raporun ayından önceki ayın TÜFE'sini ister (K-15); yalnız bu testin verisi.
    with SqliteUnitOfWork(db) as uow:
        for period, index in ((YearMonth(2026, 9), "129"), (YearMonth(2026, 12), "132")):
            point = CpiPoint(period, D(index))
            uow.cpi.upsert(scenario.SERIES, point, base="2025=100", fetched_at=RECORDED)
    return db


def _add(db: Path, *versions: SettingVersion) -> list[int]:
    with SqliteUnitOfWork(db) as uow:
        return [uow.settings.add(v, source="web", at=RECORDED) for v in versions]


def _report(db: Path, kind: ReportKind, on: date) -> Report:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        return build_report(
            uow, CONFIG, kind=kind, logical_date=on, now=scenario.NOW, cpi_series=scenario.SERIES
        )


def _payday(db: Path, on: date) -> PaydayPlan:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        return payday_plan(uow, CONFIG, on=on)


def _alerts(db: Path, on: date) -> AlertEvaluation:
    with SqliteUnitOfWork(db) as uow:
        return evaluate_alerts(uow, CONFIG, on=on, now=scenario.NOW)


def test_a_starting_version_equal_to_the_toml_changes_no_report(tmp_path: Path) -> None:
    """Migration ve ilk `config apply` öncesiyle sonrası aynı: bütün rapor türleri ve alarm."""
    without, with_start = _database(tmp_path, "toml"), _database(tmp_path, "surum")
    _add(with_start, START)

    for db_kind, on in (("weekly", date(2026, 11, 29)), ("monthly", date(2026, 11, 30))):
        assert _report(without, db_kind, on) == _report(with_start, db_kind, on)  # type: ignore[arg-type]
    assert _payday(without, date(2026, 11, 15)) == _payday(with_start, date(2026, 11, 15))
    assert _alerts(without, date(2026, 11, 29)) == _alerts(with_start, date(2026, 11, 29))


def test_a_contribution_from_january_does_not_change_the_october_report(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path, "katki")
    october = _report(db, "monthly", date(2026, 10, 31))
    _add(db, START, JANUARY)

    assert _report(db, "monthly", date(2026, 10, 31)) == october
    november = _report(db, "monthly", date(2026, 11, 30))
    january = _report(db, "monthly", date(2027, 1, 31))
    assert november.rebalance is not None
    assert january.rebalance is not None
    assert (november.rebalance.contribution, january.rebalance.contribution) == (D(1000), D(1200))
    assert _payday(db, date(2027, 1, 15)).contribution == D(1200)


def test_a_cancelled_version_is_not_applied_and_keeps_its_row(tmp_path: Path) -> None:
    db = _database(tmp_path, "vazgec")
    _, planned = _add(db, START, JANUARY)
    with SqliteUnitOfWork(db) as uow:
        uow.settings.cancel(planned, reason="yanlış tutar", at=RECORDED)

    january = _report(db, "monthly", date(2027, 1, 31))

    assert january.rebalance is not None
    assert january.rebalance.contribution == D(1000)
    with SqliteUnitOfWork(db, readonly=True) as uow:
        assert len(uow.settings.list()) == 2


def test_targets_follow_the_version_in_force_on_the_report_day(tmp_path: Path) -> None:
    db = _database(tmp_path, "hedef")
    shifted = replace(
        START,
        effective_from=date(2026, 11, 20),
        targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")},
    )
    _add(db, START, shifted)

    before = {
        line.asset_class: line.target
        for line in _report(db, "weekly", date(2026, 11, 19)).allocation
    }
    after = {
        line.asset_class: line.target
        for line in _report(db, "weekly", date(2026, 11, 29)).allocation
    }

    assert before == {"hisse": D("0.6"), "dusuk_risk": D("0.4")}
    assert after == {"hisse": D("0.7"), "dusuk_risk": D("0.3")}


def test_each_month_takes_its_payday_from_the_database(tmp_path: Path) -> None:
    db = _database(tmp_path, "maas")
    _add(db, START, replace(START, effective_from=date(2027, 1, 1), payday=20))

    with SqliteUnitOfWork(db, readonly=True) as uow:
        schedule = payday_for(uow, CONFIG)

    assert (schedule(YearMonth(2026, 12)), schedule(YearMonth(2027, 1))) == (15, 20)


def test_a_valid_version_is_added_and_a_broken_one_is_refused(migrated_db: Path) -> None:
    raised = replace(START, effective_from=TODAY, monthly_contribution=D(1200))
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.settings.add(START, source="toml", at=RECORDED)
        added = add_version(uow, CONFIG, raised, source="cli", today=TODAY, at=RECORDED)
        past = replace(raised, effective_from=date(2026, 11, 24))
        with pytest.raises(ConfigError) as refused:
            add_version(uow, CONFIG, past, source="cli", today=TODAY, at=RECORDED)
        rows = uow.settings.list()

    assert [(row.id, row.source, row.version) for row in rows] == [
        (1, "toml", START),
        (added, "cli", raised),
    ]
    assert [str(issue) for issue in refused.value.issues] == [
        "effective_from: yürürlük günü en erken bugün (2026-11-25) olabilir."
    ]


def _cancel_setup(db: Path) -> None:
    with SqliteUnitOfWork(db) as uow:
        for version in (
            START,
            JANUARY,
            replace(JANUARY, effective_from=date(2027, 2, 1)),
            replace(START, effective_from=TODAY, monthly_contribution=D(1100)),
        ):
            uow.settings.add(version, source="web", at=RECORDED)
        uow.settings.cancel(3, reason="yanlış ay", at=RECORDED)


def test_a_planned_version_is_cancelled_with_its_reason_and_keeps_its_row(
    migrated_db: Path,
) -> None:
    _cancel_setup(migrated_db)
    with SqliteUnitOfWork(migrated_db) as uow:
        cancelled = cancel_version(uow, 2, reason=" yanlış tutar ", today=TODAY, at=RECORDED)

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        rows = uow.settings.list()
    assert cancelled == JANUARY
    assert (len(rows), rows[1].cancel_reason, rows[1].cancelled_at) == (
        4,
        "yanlış tutar",
        RECORDED,
    )


@pytest.mark.parametrize(
    ("setting_id", "reason", "message"),
    [
        (2, "  ", "Vazgeçme gerekçesi boş olamaz."),
        (99, "yanlış", "99 numaralı ayar sürümü yok."),
        (3, "yanlış", "3 numaralı ayar sürümünden zaten vazgeçilmiş."),
        (
            1,
            "yanlış",
            "1 numaralı ayar sürümü yürürlüğe girmiş; vazgeçilemez. Değiştirmek için yeni bir"
            " sürüm ekle.",
        ),
        (
            4,
            "yanlış",
            "4 numaralı ayar sürümü yürürlüğe girmiş; vazgeçilemez. Değiştirmek için yeni bir"
            " sürüm ekle.",
        ),
    ],
)
def test_only_a_planned_version_can_be_cancelled(
    migrated_db: Path, setting_id: int, reason: str, message: str
) -> None:
    _cancel_setup(migrated_db)
    with pytest.raises(DomainError) as refused, SqliteUnitOfWork(migrated_db) as uow:
        cancel_version(uow, setting_id, reason=reason, today=TODAY, at=RECORDED)

    assert str(refused.value) == message


def test_a_proposal_starts_from_the_version_in_force_on_its_day(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.settings.add(START, source="toml", at=RECORDED)
        uow.settings.add(JANUARY, source="cli", at=RECORDED)
        retargeted = {"hisse": D("0.7"), "dusuk_risk": D("0.3")}
        february = propose(
            uow, CONFIG, effective_from=date(2027, 2, 1), today=TODAY, targets=retargeted
        )
        december = propose(
            uow, CONFIG, effective_from=date(2026, 12, 1), today=TODAY, targets=retargeted
        )

    assert february.base == JANUARY
    assert february.version == replace(JANUARY, effective_from=date(2027, 2, 1), targets=retargeted)
    assert (february.changed, february.issues, february.overridden_on) == (("targets",), (), ())
    assert december.base == START
    assert december.overridden_on == (date(2027, 1, 1),)


def test_a_proposal_that_changes_nothing_or_breaks_a_rule_has_issues(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.settings.add(START, source="toml", at=RECORDED)
        same = propose(uow, CONFIG, effective_from=TODAY, today=TODAY, contribution=D("1000.00"))
        mid_month = propose(uow, CONFIG, effective_from=date(2026, 12, 10), today=TODAY, payday=20)

    assert [str(issue) for issue in same.issues] == [
        "ayar: o günkü ayarla aynı; yeni sürüm gerekmiyor."
    ]
    assert [str(issue) for issue in mid_month.issues] == [
        "effective_from: maaş günü değişikliği yalnız bir ayın 1'inden geçerli olabilir."
    ]


def test_there_is_nothing_to_propose_before_the_first_config_apply(migrated_db: Path) -> None:
    with pytest.raises(DomainError) as refused, SqliteUnitOfWork(migrated_db) as uow:
        propose(uow, CONFIG, effective_from=TODAY, today=TODAY, contribution=D(1200))

    assert str(refused.value) == (
        "Ayarların başlangıç sürümü yok; önce `ft config apply` çalıştır."
    )


def test_the_history_shows_each_version_with_its_state_and_change(migrated_db: Path) -> None:
    today_raise = replace(START, effective_from=TODAY, monthly_contribution=D(1100))
    corrected = replace(JANUARY, monthly_contribution=D(1300))
    february = replace(corrected, effective_from=date(2027, 2, 1), payday=20)
    with SqliteUnitOfWork(migrated_db) as uow:
        for version in (START, today_raise, JANUARY, corrected, february):
            uow.settings.add(version, source="web", at=RECORDED)
        uow.settings.cancel(5, reason="yanlış ay", at=RECORDED)
        history = setting_history(uow, today=TODAY)

    def summary(row: HistoryRow) -> tuple[int, str, tuple[str, ...], SettingVersion | None]:
        return row.stored.id, row.state, row.changed, row.previous

    assert [summary(row) for row in history] == [
        (1, "past", (), None),
        (2, "in_force", ("monthly_contribution",), START),
        (3, "replaced", ("monthly_contribution",), today_raise),
        (4, "planned", ("monthly_contribution",), JANUARY),
        (5, "cancelled", ("payday",), corrected),
    ]
