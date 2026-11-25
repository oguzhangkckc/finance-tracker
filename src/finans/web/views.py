"""Sayfaların verisi: Telegram ve metin raporuyla aynı `Report` nesnesi (K-104)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finans import bootstrap
from finans.application.backup import BackupCheck, verify_backups
from finans.application.doctor import Check
from finans.application.history import (
    MonthContribution,
    ValuePoint,
    monthly_contributions,
    value_history,
)
from finans.application.price_refresh import RefreshStatus, refresh_status, request_refresh
from finans.application.report import ReportKind, build_report, payday_plan
from finans.application.settings import payday_for
from finans.contracts.display import class_label
from finans.contracts.report import HoldingLine, LotLine, Report
from finans.domain.models import DomainError, YearMonth
from finans.domain.portfolio import ConfigError, PortfolioConfig
from finans.domain.schedule import logical_date
from finans.ports.clock import BUSINESS_TZ, Clock
from finans.ports.repositories import StoredAlertEvent, StoredRun, StoredTransaction
from finans.settings import Settings

STALE_CHECK = "bayatlık"
GENERAL_STALE_CHECK = "genel bayatlık"
PAGE_ERRORS = (DomainError, bootstrap.SetupError, bootstrap.ProfileError)


class PageError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SystemView:
    checks: list[Check]
    runs: list[StoredRun]
    backups: list[BackupCheck]


def load_config(settings: Settings) -> PortfolioConfig:
    """Config yalnızca okunur; hedefler ve katkı oradadır (K-123 (10))."""
    if settings.portfolio_path is None:
        raise PageError("FT_PORTFOLIO_PATH tanımlı değil.")
    return bootstrap.portfolio_source().load(settings.portfolio_path)


def load_report(
    settings: Settings, clock: Clock, *, kind: ReportKind = "weekly", on: date | None = None
) -> Report:
    config = load_config(settings)
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return build_report(
            uow,
            config,
            kind=kind,
            logical_date=on or clock.today(),
            now=clock.now(),
            cpi_series=settings.cpi_series,
            profile=settings.profile,
        )


def stale_by_instrument(report: Report) -> dict[str, str]:
    """Bayatlık uyarısı `ft data check` ile aynı kurallardan gelir (K-120)."""
    return {
        issue.instrument: issue.message
        for issue in report.data_issues
        if issue.check == STALE_CHECK and issue.instrument is not None
    }


def general_staleness(report: Report) -> list[str]:
    """Hiçbir fona fiyat gelmiyorsa fon bazlı kural tetiklenmez; genel kural sayfanın başında."""
    return [issue.message for issue in report.data_issues if issue.check == GENERAL_STALE_CHECK]


def report_text(settings: Settings, clock: Clock, kind: ReportKind) -> str:
    """Telegram'a giden metnin aynısı; TL tutarları burada gizlenmez."""
    return bootstrap.report_renderer("text").report(load_report(settings, clock, kind=kind))


def payday_text(settings: Settings, clock: Clock) -> str:
    config = load_config(settings)
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        local = clock.now().astimezone(BUSINESS_TZ)
        day = logical_date("payday", local, payday=payday_for(uow, config))
        plan = payday_plan(uow, config, on=day, profile=settings.profile)
    return bootstrap.report_renderer("text").payday(plan)


def quiet_ended_on(settings: Settings) -> date | None:
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return uow.allocation_state.quiet_ended_on()


def class_names(settings: Settings) -> Mapping[str, str]:
    return load_config(settings).class_labels


@dataclass(frozen=True, slots=True)
class TransactionRow:
    stored: StoredTransaction
    asset_class: str
    class_name: str
    amount: Decimal


def transaction_rows(settings: Settings) -> list[TransactionRow]:
    """İşlemler tablosunun satırları; tutar adet × birim fiyattır (komisyon ayrı sütunda)."""
    try:
        labels = load_config(settings).class_labels
    except (PageError, ConfigError):
        # Sınıf adı yalnız gösterim içindir; config okunamazsa ad koddan türetilir (doctor uyarır).
        labels = {}
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        stored = uow.transactions.list(include_voided=True)
        classes = {
            item.instrument.code: item.instrument.asset_class
            for item in uow.instruments.list(include_inactive=True)
        }
    rows = []
    for item in stored:
        tx = item.transaction
        asset_class = classes.get(tx.instrument, "")
        name = class_label(asset_class, labels) if asset_class else ""
        rows.append(TransactionRow(item, asset_class, name, tx.units * tx.unit_price))
    return rows


def refresh_view(settings: Settings, clock: Clock) -> RefreshStatus:
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return refresh_status(uow, bootstrap.refresh_requests(settings), now=clock.now())


def ask_for_refresh(settings: Settings, clock: Clock) -> RefreshStatus:
    """Web fiyat çekmez; istek dosyası bırakır, işi systemd başlatır (K-106, K-123)."""
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return request_refresh(uow, bootstrap.refresh_requests(settings), now=clock.now())


def system_view(settings: Settings, clock: Clock) -> SystemView:
    """Doctor sırların değerini yazmaz; yalnız tanımlı olup olmadığını (K-92)."""
    checks = bootstrap.run_doctor(settings)
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        # İş geçmişi tablosu bütün kayıtları sayfalar (K-129).
        runs = uow.runs.recent()
    directory = settings.backup_dir
    backups = verify_backups(directory) if directory is not None and directory.is_dir() else []
    return SystemView(checks, runs, backups)


@dataclass(frozen=True, slots=True)
class HoldingRow:
    index: int
    line: HoldingLine
    class_name: str


@dataclass(frozen=True, slots=True)
class LotRow:
    index: int
    line: LotLine
    # Kâr/zarar = değer - maliyet; fiyatı olmayan lotta yok.
    gain: Decimal | None


@dataclass(frozen=True, slots=True)
class AlertEventRow:
    stored: StoredAlertEvent
    asset_class: str
    class_name: str
    day: date


def holding_rows(report: Report, labels: Mapping[str, str]) -> list[HoldingRow]:
    return [
        HoldingRow(index, line, class_label(line.asset_class, labels))
        for index, line in enumerate(report.holdings)
    ]


def lot_rows(report: Report) -> list[LotRow]:
    return [
        LotRow(index, lot, None if lot.value is None else lot.value - lot.cost)
        for index, lot in enumerate(report.lots)
    ]


def alert_event_rows(settings: Settings) -> list[AlertEventRow]:
    labels = class_names(settings)
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        events = uow.alerts.events()
    rows = []
    for stored in events:
        asset_class = stored.event.fingerprint.removeprefix("drift:")
        local_day = stored.event.occurred_at.astimezone(BUSINESS_TZ).date()
        rows.append(AlertEventRow(stored, asset_class, class_label(asset_class, labels), local_day))
    return rows


@dataclass(frozen=True, slots=True)
class ValueChart:
    points: list[ValuePoint]
    # Son noktada değer - enflasyona göre güncellenmiş yatırım; artıysa reel kazanç (K-129).
    real_gap: Decimal | None
    estimated_period: YearMonth | None


def value_chart_view(settings: Settings, clock: Clock) -> ValueChart:
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        points = value_history(uow, end=clock.today(), cpi_series=settings.cpi_series)
    last = next(
        (p for p in reversed(points) if p.value is not None and p.adjusted is not None), None
    )
    gap = (
        None
        if last is None or last.value is None or last.adjusted is None
        else last.value - last.adjusted
    )
    estimated = next((p.cpi_period for p in reversed(points) if p.estimated), None)
    return ValueChart(points, gap, estimated)


CONTRIBUTION_MONTHS = 12


def contribution_view(settings: Settings, clock: Clock) -> list[MonthContribution]:
    """Planlanan katkı W2d'ye kadar portfolio.toml'dan (K-129)."""
    planned = load_config(settings).monthly_contribution
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return monthly_contributions(
            uow, end=clock.today(), months=CONTRIBUTION_MONTHS, planned=planned
        )
