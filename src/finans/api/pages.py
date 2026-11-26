"""Okuma sayfalarının yanıtları (K-138): web'deki sayfaların verisi, aynı `Report` nesnesinden.

Rakamlar biçimlenmez; Türkçe gösterim istemcidedir. Ayar değişikliği satırları ve uyarılar
kullanıcıya giden ileti olduğu için sunucuda Türkçe üretilir."""

from datetime import date, datetime
from typing import Literal

from finans.api.models import DecimalStr, Model
from finans.api.tables import Table
from finans.application.history import MonthContribution
from finans.application.price_refresh import RefreshStatus
from finans.application.settings import STATE_LABELS, HistoryRow, SettingState
from finans.contracts.display import class_label
from finans.contracts.report import AlertLine, HoldingLine, LotLine, Report
from finans.domain.portfolio import PortfolioConfig
from finans.domain.settings import SettingValues
from finans.ports.repositories import JobStatus, StoredRun
from finans.sunum.setting_writes import SettingsView, change_lines
from finans.sunum.tables import RUN_STATUS, SETTING_SOURCES
from finans.sunum.views import (
    AlertEventRow,
    HoldingRow,
    LotRow,
    SystemView,
    TransactionRow,
    ValueChart,
)


def class_names(config: PortfolioConfig) -> dict[str, str]:
    """Portföydeki her sınıfın adı; `[sinif_adlari]`'da yoksa koddan türetilir (K-128)."""
    codes = {instrument.asset_class for instrument in config.instruments} | set(config.targets)
    return {code: class_label(code, config.class_labels) for code in sorted(codes)}


class ReportPage(Model):
    report: Report
    stale: dict[str, str]
    stale_all: list[str]
    class_names: dict[str, str]


class RefreshInfo(Model):
    allowed: bool
    reason: str | None
    earliest: datetime | None
    last_sync: datetime | None


def refresh_info(status: RefreshStatus) -> RefreshInfo:
    decision = status.decision
    return RefreshInfo(
        allowed=decision.allowed,
        reason=decision.reason,
        earliest=decision.earliest,
        last_sync=status.last_sync,
    )


class ValuePointItem(Model):
    day: date
    value: DecimalStr | None
    invested: DecimalStr
    adjusted: DecimalStr | None
    cpi_period: str | None
    estimated: bool


class ValueChartData(Model):
    """Değerin seyri üç çizgidir: değer, yatırılan para, enflasyona göre güncellenmiş yatırım."""

    points: list[ValuePointItem]
    real_gap: DecimalStr | None
    estimated_period: str | None


def chart_data(chart: ValueChart) -> ValueChartData:
    return ValueChartData(
        points=[
            ValuePointItem(
                day=p.day,
                value=p.value,
                invested=p.invested,
                adjusted=p.adjusted,
                cpi_period=None if p.cpi_period is None else str(p.cpi_period),
                estimated=p.estimated,
            )
            for p in chart.points
        ],
        real_gap=chart.real_gap,
        estimated_period=None if chart.estimated_period is None else str(chart.estimated_period),
    )


class ContributionItem(Model):
    month: str
    invested: DecimalStr
    planned: DecimalStr | None


def contribution_items(months: list[MonthContribution]) -> list[ContributionItem]:
    return [
        ContributionItem(month=str(m.month), invested=m.invested, planned=m.planned) for m in months
    ]


class OverviewPage(ReportPage):
    refresh: RefreshInfo
    chart: ValueChartData


class ReturnsPage(ReportPage):
    chart: ValueChartData
    contributions: list[ContributionItem]


class ReportText(Model):
    title: str
    text: str


class HoldingItem(HoldingLine):
    class_name: str


def holding_item(row: HoldingRow) -> HoldingItem:
    return HoldingItem(**row.line.model_dump(), class_name=row.class_name)


class HoldingsPage(Model):
    table: Table[HoldingItem]
    logical_date: date
    stale: dict[str, str]


class LotItem(LotLine):
    gain: DecimalStr | None


def lot_item(row: LotRow) -> LotItem:
    return LotItem(**row.line.model_dump(), gain=row.gain)


class LotsPage(Model):
    table: Table[LotItem]
    logical_date: date


class TransactionItem(Model):
    id: int
    instrument: str
    trade_date: date
    side: Literal["BUY", "SELL"]
    units: DecimalStr
    unit_price: DecimalStr
    fee: DecimalStr
    amount: DecimalStr
    asset_class: str
    class_name: str
    external_ref: str | None
    note: str | None
    created_at: datetime
    voided_at: datetime | None
    void_reason: str | None


def transaction_item(row: TransactionRow) -> TransactionItem:
    stored = row.stored
    tx = stored.transaction
    return TransactionItem(
        id=stored.id,
        instrument=tx.instrument,
        trade_date=tx.trade_date,
        side=tx.side.value,
        units=tx.units,
        unit_price=tx.unit_price,
        fee=tx.fee,
        amount=row.amount,
        asset_class=row.asset_class,
        class_name=row.class_name,
        external_ref=stored.external_ref,
        note=stored.note,
        created_at=stored.created_at,
        voided_at=stored.voided_at,
        void_reason=stored.void_reason,
    )


class TransactionsPage(Model):
    table: Table[TransactionItem]


class AlertEventItem(Model):
    id: int
    occurred_at: datetime
    day: date
    kind: Literal["opened", "resolved"]
    direction: Literal["above", "below"]
    deviation: DecimalStr
    asset_class: str
    class_name: str
    notified_at: datetime | None


def alert_event_item(row: AlertEventRow) -> AlertEventItem:
    event = row.stored.event
    return AlertEventItem(
        id=row.stored.id,
        occurred_at=event.occurred_at,
        day=row.day,
        kind=event.kind,
        direction=event.direction,
        deviation=event.deviation,
        asset_class=row.asset_class,
        class_name=row.class_name,
        notified_at=row.stored.notified_at,
    )


class AlertsPage(Model):
    table: Table[AlertEventItem]
    alerts: list[AlertLine]
    quiet_ended: date | None
    class_names: dict[str, str]


class RunItem(Model):
    """İş kaydının ayrıntı metni (`detail`) verilmez; web'de de gösterilmez."""

    id: int
    job: str
    logical_date: date
    started_at: datetime
    finished_at: datetime | None
    status: JobStatus
    status_label: str


def run_item(run: StoredRun) -> RunItem:
    return RunItem(
        id=run.id,
        job=run.job,
        logical_date=run.logical_date,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        status_label=RUN_STATUS[run.status],
    )


class CheckItem(Model):
    name: str
    status: Literal["ok", "warn", "fail"]
    detail: str


class BackupItem(Model):
    name: str
    ok: bool
    message: str


class SystemPage(Model):
    table: Table[RunItem]
    checks: list[CheckItem]
    backups: list[BackupItem]


def system_extras(view: SystemView) -> tuple[list[CheckItem], list[BackupItem]]:
    checks = [CheckItem(name=c.name, status=c.status, detail=c.detail) for c in view.checks]
    backups = [BackupItem(name=b.name, ok=b.ok, message=b.message) for b in view.backups]
    return checks, backups


class SettingValuesData(Model):
    payday: int | None
    monthly_contribution: DecimalStr | None
    targets: dict[str, DecimalStr]


class SettingChange(Model):
    setting: str
    change: str


class SettingItem(Model):
    """`initial`: `ft config apply`'ın yazdığı başlangıç sürümü; yürürlük günü yoktur."""

    id: int
    recorded_at: datetime
    source: str
    source_label: str
    effective_from: date
    initial: bool
    values: SettingValuesData
    state: SettingState
    state_label: str
    cancelled_at: datetime | None
    cancel_reason: str | None
    changes: list[SettingChange]


def setting_values(values: SettingValues) -> SettingValuesData:
    return SettingValuesData.model_validate(
        {
            "payday": values.payday,
            "monthly_contribution": values.monthly_contribution,
            "targets": dict(values.targets),
        }
    )


def setting_item(row: HistoryRow, view: SettingsView) -> SettingItem:
    stored = row.stored
    version = stored.version
    return SettingItem(
        id=stored.id,
        recorded_at=stored.recorded_at,
        source=stored.source,
        source_label=SETTING_SOURCES[stored.source],
        effective_from=version.effective_from,
        initial=version.effective_from.year == 1,
        values=setting_values(version),
        state=row.state,
        state_label=STATE_LABELS[row.state],
        cancelled_at=stored.cancelled_at,
        cancel_reason=stored.cancel_reason,
        changes=[
            SettingChange(setting=name, change=text)
            for name, text in change_lines(row.previous, version, row.changed, view)
        ],
    )


class SettingsPage(Model):
    """`current`: bugün geçerli değerler; sürüm yoksa portfolio.toml'dakiler (K-127)."""

    table: Table[SettingItem]
    current: SettingValuesData
    current_id: int | None
    current_from: date | None
    planned: list[SettingItem]
    classes: list[str]
    class_names: dict[str, str]


def settings_extras(view: SettingsView) -> dict[str, object]:
    row = view.current_row
    current = view.current
    return {
        "current": setting_values(current),
        "current_id": None if row is None else row.stored.id,
        "current_from": (
            None
            if row is None or row.stored.version.effective_from.year == 1
            else row.stored.version.effective_from
        ),
        "planned": [setting_item(planned, view) for planned in view.planned],
        "classes": list(view.classes),
        "class_names": {code: view.cls(code) for code in view.classes},
    }


class FundOption(Model):
    code: str
    name: str


class FundOptions(Model):
    """Alışta yalnız etkin fonlar, satışta pasif fonlar da (K-51)."""

    buy: list[FundOption]
    sell: list[FundOption]
