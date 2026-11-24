"""Rapor çıktıları test veritabanından uçtan uca üretilir (build_report ve renderer'lar)."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from finans.adapters.render.json import JsonRenderer
from finans.adapters.render.text import TextRenderer
from finans.contracts.report import Report
from tests.support import report_scenario as scenario

SUNDAY = date(2026, 11, 29)
MONTH_END = date(2026, 11, 30)
TELEGRAM = TextRenderer(hide_amounts=True, payday_amounts=False, html=True)


def test_weekly_with_amounts(migrated_db: Path, snapshot: SnapshotAssertion) -> None:
    scenario.seed(migrated_db)
    report = scenario.report(migrated_db, "weekly", SUNDAY)

    assert report.data_issues == []
    assert report.quiet_period
    assert TextRenderer().report(report) == snapshot


def test_monthly_with_amounts(migrated_db: Path, snapshot: SnapshotAssertion) -> None:
    scenario.seed(migrated_db)
    report = scenario.report(migrated_db, "monthly", MONTH_END)

    assert [(lot.instrument, lot.acquired) for lot in report.lots] == [
        ("XAC", date(2026, 11, 2)),
        ("XHT", date(2026, 11, 2)),
        ("XHT", date(2026, 11, 25)),
        ("XPP", date(2026, 11, 2)),
    ]
    assert report.summary.real_same_as_nominal
    assert report.health.last_cpi_sync == scenario.CPI_FETCH
    assert TextRenderer().report(report) == snapshot


def test_monthly_as_sent_to_telegram(migrated_db: Path, snapshot: SnapshotAssertion) -> None:
    scenario.seed(migrated_db)
    text = TELEGRAM.report(scenario.report(migrated_db, "monthly", MONTH_END))

    assert "TL" not in text
    assert "`" not in text
    assert text == snapshot


def test_payday_as_sent_and_with_amounts(migrated_db: Path, snapshot: SnapshotAssertion) -> None:
    scenario.seed(migrated_db)
    plan = scenario.payday(migrated_db, date(2026, 11, 15))

    sent = TELEGRAM.payday(plan)
    local = TextRenderer().payday(plan)
    assert "<code>ft tx add</code>" in sent
    assert "TL" not in sent
    assert (sent, local) == snapshot


def test_missing_price_is_reported_not_valued(
    migrated_db: Path, snapshot: SnapshotAssertion
) -> None:
    scenario.seed(migrated_db, priced=("XHT", "XAC"), alarm=True)
    report = scenario.report(migrated_db, "weekly", SUNDAY)

    assert (report.missing_prices, report.allocation_skipped) == (["XPP"], ["XPP"])
    assert report.allocation == []
    assert (report.summary.change, report.summary.simple_return) == (None, None)
    assert not report.quiet_period
    assert [alert.deviation for alert in report.alerts] == [None]
    assert {issue.check for issue in report.data_issues} >= {"bayatlık"}
    assert TextRenderer().report(report) == snapshot


def test_missing_price_stops_the_payday_plan(migrated_db: Path) -> None:
    scenario.seed(migrated_db, priced=("XHT", "XAC"))
    plan = scenario.payday(migrated_db, date(2026, 11, 15))

    assert (plan.lines, plan.missing_prices) == ([], ["XPP"])
    assert "Dağılım önerisi hesaplanmadı: XPP için fiyat yok." in TELEGRAM.payday(plan)


def test_json_is_the_contract(migrated_db: Path, snapshot: SnapshotAssertion) -> None:
    scenario.seed(migrated_db)
    report = scenario.report(migrated_db, "monthly", MONTH_END)
    text = JsonRenderer().report(report)

    assert Report.model_validate(json.loads(text, parse_float=Decimal)) == report
    assert Decimal(json.loads(text)["summary"]["values"]["total"]) == Decimal(2780)
    assert text == snapshot
