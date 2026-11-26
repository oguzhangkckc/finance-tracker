"""Okuma uçları (K-138): web'deki her sayfanın verisi; profil adresle seçilir (K-125).

Decimal taşıyan her uç CanonicalJSONResponse döndürür; `response_model` yalnız şema içindir."""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from finans.api.context import ApiContext, context, profile
from finans.api.encoding import CanonicalJSONResponse
from finans.api.errors import page_errors
from finans.api.models import PAGE_RESPONSES
from finans.api.pages import (
    AlertsPage,
    FundOption,
    FundOptions,
    HoldingsPage,
    LotsPage,
    OverviewPage,
    ReportPage,
    ReportText,
    ReturnsPage,
    SettingsPage,
    SystemPage,
    TransactionsPage,
    alert_event_item,
    chart_data,
    class_names,
    contribution_items,
    holding_item,
    lot_item,
    refresh_info,
    run_item,
    setting_item,
    settings_extras,
    system_extras,
    transaction_item,
)
from finans.api.tables import table_data, table_parameters
from finans.application.report import ReportKind
from finans.ports.clock import Clock
from finans.settings import Settings
from finans.sunum.setting_writes import settings_view
from finans.sunum.table import table
from finans.sunum.tables import ALERT_EVENTS, HOLDINGS, LOTS, RUNS, SETTINGS, TRANSACTIONS
from finans.sunum.views import (
    alert_event_rows,
    contribution_view,
    general_staleness,
    holding_rows,
    load_config,
    load_report,
    lot_rows,
    payday_text,
    quiet_ended_on,
    refresh_view,
    report_text,
    stale_by_instrument,
    system_view,
    transaction_rows,
    value_chart_view,
)
from finans.sunum.writes import choices

type ReportSlug = Literal["haftalik", "aylik", "maas-gunu"]
TITLES: Final[dict[ReportSlug, str]] = {
    "haftalik": "Haftalık rapor",
    "aylik": "Aylık rapor",
    "maas-gunu": "Maaş günü",
}
KINDS: Final[dict[ReportSlug, ReportKind]] = {"haftalik": "weekly", "aylik": "monthly"}

router = APIRouter(prefix="/api/{profil}", tags=["okuma"], responses=PAGE_RESPONSES)
Conf = Annotated[Settings, Depends(profile)]
Ctx = Annotated[ApiContext, Depends(context)]


def _report_page(conf: Settings, clock: Clock, kind: ReportKind) -> dict[str, object]:
    report = load_report(conf, clock, kind=kind)
    return {
        "report": report,
        "stale": stale_by_instrument(report),
        "stale_all": general_staleness(report),
        "class_names": class_names(load_config(conf)),
    }


@router.get("/ozet", response_model=OverviewPage)
def overview(conf: Conf, ctx: Ctx) -> Response:
    with page_errors():
        page = OverviewPage.model_validate(
            {
                **_report_page(conf, ctx.clock, "weekly"),
                "refresh": refresh_info(refresh_view(conf, ctx.clock)),
                "chart": chart_data(value_chart_view(conf, ctx.clock)),
            }
        )
    return CanonicalJSONResponse(page)


@router.get("/dagilim", response_model=ReportPage)
def allocation(conf: Conf, ctx: Ctx) -> Response:
    with page_errors():
        page = ReportPage.model_validate(_report_page(conf, ctx.clock, "weekly"))
    return CanonicalJSONResponse(page)


@router.get("/getiri", response_model=ReturnsPage)
def returns(conf: Conf, ctx: Ctx) -> Response:
    """Para ağırlıklı getiri ve lotlar yalnız aylık raporda."""
    with page_errors():
        page = ReturnsPage.model_validate(
            {
                **_report_page(conf, ctx.clock, "monthly"),
                "chart": chart_data(value_chart_view(conf, ctx.clock)),
                "contributions": contribution_items(contribution_view(conf, ctx.clock)),
            }
        )
    return CanonicalJSONResponse(page)


@router.get("/raporlar/{tur}", response_model=ReportText)
def report(conf: Conf, ctx: Ctx, tur: ReportSlug) -> Response:
    """Telegram'a giden metnin aynısı; TL tutarları burada gizlenmez."""
    with page_errors():
        if tur == "maas-gunu":
            text = payday_text(conf, ctx.clock)
        else:
            text = report_text(conf, ctx.clock, KINDS[tur])
    return CanonicalJSONResponse(ReportText(title=TITLES[tur], text=text))


@router.get("/varliklar", response_model=HoldingsPage, openapi_extra=table_parameters(HOLDINGS))
def holdings(conf: Conf, ctx: Ctx, request: Request) -> Response:
    with page_errors():
        monthly = load_report(conf, ctx.clock, kind="monthly")
        rows = holding_rows(monthly, load_config(conf).class_labels)
    view = table(rows, request.query_params, HOLDINGS)
    page = HoldingsPage(
        table=table_data(view, holding_item),
        logical_date=monthly.logical_date,
        stale=stale_by_instrument(monthly),
    )
    return CanonicalJSONResponse(page)


@router.get("/varliklar/lotlar", response_model=LotsPage, openapi_extra=table_parameters(LOTS))
def lots(conf: Conf, ctx: Ctx, request: Request) -> Response:
    with page_errors():
        monthly = load_report(conf, ctx.clock, kind="monthly")
    view = table(lot_rows(monthly), request.query_params, LOTS)
    page = LotsPage(table=table_data(view, lot_item), logical_date=monthly.logical_date)
    return CanonicalJSONResponse(page)


@router.get(
    "/islemler", response_model=TransactionsPage, openapi_extra=table_parameters(TRANSACTIONS)
)
def transactions(conf: Conf, request: Request) -> Response:
    with page_errors():
        rows = transaction_rows(conf)
    view = table(rows, request.query_params, TRANSACTIONS)
    return CanonicalJSONResponse(TransactionsPage(table=table_data(view, transaction_item)))


@router.get("/alarmlar", response_model=AlertsPage, openapi_extra=table_parameters(ALERT_EVENTS))
def alerts(conf: Conf, ctx: Ctx, request: Request) -> Response:
    with page_errors():
        weekly = load_report(conf, ctx.clock, kind="weekly")
        rows = alert_event_rows(conf)
        quiet_ended = quiet_ended_on(conf)
        names = class_names(load_config(conf))
    view = table(rows, request.query_params, ALERT_EVENTS)
    page = AlertsPage(
        table=table_data(view, alert_event_item),
        alerts=weekly.alerts,
        quiet_ended=quiet_ended,
        class_names=names,
    )
    return CanonicalJSONResponse(page)


@router.get("/sistem", response_model=SystemPage, openapi_extra=table_parameters(RUNS))
def system(conf: Conf, ctx: Ctx, request: Request) -> Response:
    """Doctor sırların değerini yazmaz, yalnız tanımlı olup olmadığını (K-92)."""
    with page_errors():
        view = system_view(conf, ctx.clock)
    checks, backups = system_extras(view)
    rows = table(view.runs, request.query_params, RUNS)
    page = SystemPage(table=table_data(rows, run_item), checks=checks, backups=backups)
    return CanonicalJSONResponse(page)


@router.get("/ayarlar", response_model=SettingsPage, openapi_extra=table_parameters(SETTINGS))
def settings(conf: Conf, ctx: Ctx, request: Request) -> Response:
    with page_errors():
        view = settings_view(conf, ctx.clock.today())
    rows = table(view.history, request.query_params, SETTINGS)
    page = SettingsPage.model_validate(
        {
            "table": table_data(rows, lambda row: setting_item(row, view)),
            **settings_extras(view),
        }
    )
    return CanonicalJSONResponse(page)


@router.get("/secenekler", response_model=FundOptions)
def options(conf: Conf) -> Response:
    with page_errors():
        buy, sell = choices(conf, "alis"), choices(conf, "satis")
    return CanonicalJSONResponse(
        FundOptions(
            buy=[FundOption(code=code, name=name) for code, name in buy],
            sell=[FundOption(code=code, name=name) for code, name in sell],
        )
    )
