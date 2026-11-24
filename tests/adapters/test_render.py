import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from syrupy.assertion import SnapshotAssertion

from finans.adapters.render.json import JsonRenderer
from finans.adapters.render.text import TextRenderer, money, percent, points
from finans.contracts.report import (
    AlertLine,
    AllocationLine,
    DataIssueLine,
    HoldingLine,
    Inflation,
    LotLine,
    PaydayLine,
    PaydayPlan,
    Provenance,
    RebalanceLine,
    RebalancePlan,
    Report,
    ReturnFigure,
    Summary,
    SystemHealth,
    ValueSplit,
)

D = Decimal
NOW = datetime(2026, 11, 30, 9, 0, tzinfo=UTC)
WEEKLY = Report(
    kind="weekly",
    logical_date=date(2026, 11, 29),
    summary=Summary(
        values=ValueSplit(in_allocation=D(2275), out_of_allocation=D(505), total=D(2780)),
        previous_total=D(2550),
        weekly_change=D(120) / D(2550),
        simple_return=D(2780) / D(2610) - 1,
        realized_pnl=D(0),
    ),
    holdings=[
        HoldingLine(
            instrument="XAC",
            asset_class="acil_durum",
            allocation=False,
            units=D(10),
            cost=D(500),
            value=D(505),
            price=D("50.5"),
            price_date=date(2026, 11, 27),
            source="tefas",
            simple_return=D("0.01"),
        ),
        HoldingLine(
            instrument="XHT",
            asset_class="hisse",
            allocation=True,
            units=D(110),
            cost=D(1110),
            value=D(1265),
            price=D("11.5"),
            price_date=date(2026, 11, 27),
            source="tefas",
            simple_return=D(1265) / D(1110) - 1,
        ),
        HoldingLine(
            instrument="XPP",
            asset_class="dusuk_risk",
            allocation=True,
            units=D(50),
            cost=D(1000),
            value=None,
            price=None,
            price_date=None,
            source=None,
            simple_return=None,
        ),
    ],
    allocation=[
        AllocationLine(
            asset_class="dusuk_risk",
            value=D(1010),
            weight=D(1010) / D(2275),
            target=D("0.4"),
            deviation=D(1010) / D(2275) - D("0.4"),
        ),
        AllocationLine(
            asset_class="hisse",
            value=D(1265),
            weight=D(1265) / D(2275),
            target=D("0.6"),
            deviation=D(1265) / D(2275) - D("0.6"),
        ),
    ],
    quiet_period=True,
    rebalance=None,
    alerts=[
        AlertLine(
            asset_class="hisse",
            direction="below",
            deviation=D(1265) / D(2275) - D("0.6"),
            opened_at=datetime(2026, 11, 24, 18, 35, tzinfo=UTC),
        )
    ],
    data_issues=[
        DataIssueLine(
            check="bayatlık",
            level="warn",
            instrument="XPP",
            day=None,
            message="hiç fiyat yok; `ft sync prices` çalıştır",
        )
    ],
    provenance=Provenance(
        price_dates={"XAC": date(2026, 11, 27), "XHT": date(2026, 11, 27)},
        cpi_period=None,
        generated_at=NOW,
    ),
    health=SystemHealth(
        last_price_sync=datetime(2026, 11, 27, 18, 31, tzinfo=UTC),
        last_cpi_sync=None,
        failed_jobs_7d=1,
    ),
)
MONTHLY = WEEKLY.model_copy(
    update={
        "kind": "monthly",
        "logical_date": date(2026, 11, 30),
        "summary": WEEKLY.summary.model_copy(
            update={
                "money_weighted": ReturnFigure(status="ok", rate=D("0.0817"), annualized=False),
                "real_money_weighted": ReturnFigure(
                    status="ok", rate=D("0.0817"), annualized=False
                ),
            }
        ),
        "holdings": [
            WEEKLY.holdings[0].model_copy(update={"real_return": D("0.01")}),
            *WEEKLY.holdings[1:],
        ],
        "lots": [
            LotLine(
                instrument="XHT",
                acquired=date(2026, 11, 2),
                units=D(100),
                cost=D(1000),
                value=D(1150),
                real_return=D("0.15"),
                cpi_period="2026-10",
            )
        ],
        "quiet_period": False,
        "rebalance": RebalancePlan(
            contribution=D(1000),
            lines=[
                RebalanceLine(asset_class="dusuk_risk", instrument="XPP", amount=D("300.00")),
                RebalanceLine(asset_class="hisse", instrument="XHT", amount=D("700.00")),
            ],
        ),
        "alerts": [],
        "data_issues": [],
        "inflation": Inflation(
            cpi_series="TP.TUKFIY2025.GENEL", valuation_period="2026-10", annual_inflation=D("0.3")
        ),
    }
)
PAYDAY = PaydayPlan(
    logical_date=date(2026, 11, 15),
    contribution=D(1000),
    lines=[
        PaydayLine(asset_class="dusuk_risk", instrument="XPP", amount=D("300.00"), share=D("0.3")),
        PaydayLine(asset_class="hisse", instrument="XHT", amount=D("700.00"), share=D("0.7")),
    ],
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (D("1234.565"), "1.234,56 TL"),
        (D("1234.575"), "1.234,58 TL"),
        (D("-1000000"), "-1.000.000,00 TL"),
        (D(0), "0,00 TL"),
        (D("0.5"), "0,50 TL"),
    ],
)
def test_money_uses_turkish_separators_and_banker_rounding(value: Decimal, expected: str) -> None:
    assert money(value) == expected


def test_percent_and_points_show_signs_where_asked() -> None:
    assert percent(D("0.047058")) == "%4,71"
    assert percent(D("0.047058"), signed=True) == "+%4,71"
    assert percent(D("-0.012"), signed=True) == "-%1,20"
    assert percent(D("0.444"), places=1) == "%44,4"
    assert points(D("0.04396")) == "+4,4 puan"
    assert points(D("-0.04396")) == "-4,4 puan"


def test_weekly_text(snapshot: SnapshotAssertion) -> None:
    assert TextRenderer().report(WEEKLY) == snapshot


def test_monthly_text(snapshot: SnapshotAssertion) -> None:
    assert TextRenderer().report(MONTHLY) == snapshot


def test_hidden_amounts_leave_only_percentages(snapshot: SnapshotAssertion) -> None:
    text = TextRenderer(hide_amounts=True).report(MONTHLY)
    assert "TL" not in text
    assert text == snapshot


@pytest.mark.parametrize(
    ("figure", "expected"),
    [
        (
            ReturnFigure(status="out_of_range"),
            "Zamanlama nedeniyle para ağırlıklı getiri anlamlı değil.",
        ),
        (ReturnFigure(status="undefined"), "Para ağırlıklı getiri: hesaplanamadı"),
        (
            ReturnFigure(status="ok", rate=D("0.1234"), annualized=True),
            "Yıllık para ağırlıklı getiri (XIRR): %12,34",
        ),
    ],
)
def test_money_weighted_states(figure: ReturnFigure, expected: str) -> None:
    summary = MONTHLY.summary.model_copy(update={"money_weighted": figure})
    assert expected in TextRenderer().report(MONTHLY.model_copy(update={"summary": summary}))


@pytest.mark.parametrize(
    ("rebalance", "expected"),
    [
        (None, "Katkı tanımlı değil."),
        (RebalancePlan(contribution=D(0), lines=[]), "Bu ay katkı 0."),
    ],
)
def test_undefined_and_zero_contribution_notes(
    rebalance: RebalancePlan | None, expected: str
) -> None:
    text = TextRenderer().report(MONTHLY.model_copy(update={"rebalance": rebalance}))
    assert expected in text


def test_payday_message_hides_amounts_by_its_own_setting(snapshot: SnapshotAssertion) -> None:
    hidden = TextRenderer(hide_amounts=False, payday_amounts=False).payday(PAYDAY)
    shown = TextRenderer(hide_amounts=True, payday_amounts=True).payday(PAYDAY)
    assert "TL" not in hidden
    assert "700,00 TL" in shown
    assert (hidden, shown) == snapshot


def test_sections_are_separated_by_blank_lines_for_splitting() -> None:
    sections = TextRenderer().report(WEEKLY).split("\n\n")
    assert sections[0].startswith("Haftalık rapor (2026-11-29)")
    assert sections[-1].startswith("Sistem:")


def test_json_is_the_contract_with_decimals_as_text(snapshot: SnapshotAssertion) -> None:
    text = JsonRenderer().report(MONTHLY)
    data = json.loads(text)
    assert data["schema_version"] == "1.0"
    assert data["summary"]["values"]["total"] == "2780"
    assert Report.model_validate(json.loads(text, parse_float=Decimal)) == MONTHLY
    assert text == snapshot
    assert json.loads(JsonRenderer().payday(PAYDAY))["lines"][1]["amount"] == "700.00"
