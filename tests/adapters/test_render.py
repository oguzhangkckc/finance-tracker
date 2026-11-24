from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.render.text import TextRenderer
from finans.contracts.report import (
    DataIssueLine,
    PaydayPlan,
    RebalancePlan,
    Report,
    ReturnFigure,
)
from tests.support import report_scenario as scenario

D = Decimal


@pytest.fixture
def monthly(migrated_db: Path) -> Report:
    scenario.seed(migrated_db)
    return scenario.report(migrated_db, "monthly", date(2026, 11, 30))


@pytest.mark.parametrize(
    ("figure", "expected"),
    [
        (
            ReturnFigure(status="out_of_range"),
            "Zamanlama nedeniyle para ağırlıklı getiri anlamlı değil.",
        ),
        (ReturnFigure(status="undefined"), "Para ağırlıklı getiri (dağılım içi): hesaplanamadı"),
        (
            ReturnFigure(status="ok", rate=D("0.1234"), annualized=True),
            "Yıllık para ağırlıklı getiri (XIRR), dağılım içi: %12,34",
        ),
    ],
)
def test_money_weighted_states(monthly: Report, figure: ReturnFigure, expected: str) -> None:
    summary = monthly.summary.model_copy(update={"money_weighted": figure})
    assert expected in TextRenderer().report(monthly.model_copy(update={"summary": summary}))


@pytest.mark.parametrize(
    ("rebalance", "expected"),
    [
        (None, "Katkı tanımlı değil."),
        (RebalancePlan(contribution=D(0), lines=[]), "Bu ay katkı 0."),
    ],
)
def test_undefined_and_zero_contribution_notes(
    monthly: Report, rebalance: RebalancePlan | None, expected: str
) -> None:
    text = TextRenderer().report(monthly.model_copy(update={"rebalance": rebalance}))
    assert expected in text


def test_sections_are_separated_by_blank_lines_for_splitting(monthly: Report) -> None:
    sections = TextRenderer().report(monthly).split("\n\n")
    assert sections[0].startswith("Aylık rapor (2026-11-30)")
    assert sections[-1].startswith("Sistem:")


def test_html_escapes_text_and_marks_commands_as_code(monthly: Report) -> None:
    issue = DataIssueLine(
        check="deneme", level="warn", instrument=None, day=None, message="a < b; `ft sync prices`"
    )
    report = monthly.model_copy(update={"data_issues": [issue]})
    assert "! deneme: a &lt; b; <code>ft sync prices</code>" in TextRenderer(html=True).report(
        report
    )
    assert "! deneme: a < b; `ft sync prices`" in TextRenderer().report(report)


def test_sanal_report_and_payday_open_with_the_notice_in_text_only(monthly: Report) -> None:
    sanal = monthly.model_copy(update={"profile": "sanal"})
    plan = PaydayPlan(profile="sanal", logical_date=date(2026, 11, 15), contribution=D(0), lines=[])

    assert TextRenderer().report(sanal).splitlines()[0] == "SANAL — gerçek alım değil"
    assert TextRenderer().payday(plan).splitlines()[0] == "SANAL — gerçek alım değil"
    assert "SANAL" not in TextRenderer(html=True).report(sanal)
    assert "SANAL" not in TextRenderer().report(monthly)
