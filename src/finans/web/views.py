"""Sayfaların verisi: Telegram ve metin raporuyla aynı `Report` nesnesi (K-104)."""

from dataclasses import dataclass
from datetime import date, timedelta

from finans import bootstrap
from finans.application.backup import BackupCheck, verify_backups
from finans.application.doctor import Check
from finans.application.report import ReportKind, build_report, payday_plan
from finans.contracts.report import Report
from finans.domain.models import DomainError
from finans.domain.portfolio import PortfolioConfig
from finans.domain.schedule import logical_date
from finans.ports.clock import BUSINESS_TZ, Clock
from finans.ports.repositories import StoredRun, StoredTransaction
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


def _config(settings: Settings) -> PortfolioConfig:
    """Config yalnızca okunur; hedefler ve katkı oradadır (K-123 (10))."""
    if settings.portfolio_path is None:
        raise PageError("FT_PORTFOLIO_PATH tanımlı değil.")
    return bootstrap.portfolio_source().load(settings.portfolio_path)


def load_report(
    settings: Settings, clock: Clock, *, kind: ReportKind = "weekly", on: date | None = None
) -> Report:
    config = _config(settings)
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return build_report(
            uow,
            config,
            kind=kind,
            logical_date=on or clock.today(),
            contribution=config.monthly_contribution,
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
    config = _config(settings)
    if config.payday is None:
        raise PageError("portfolio.toml'da [contribution] payday tanımlı değil.")
    day = logical_date("payday", clock.now().astimezone(BUSINESS_TZ), payday=config.payday)
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        plan = payday_plan(
            uow, config, on=day, contribution=config.monthly_contribution, profile=settings.profile
        )
    return bootstrap.report_renderer("text").payday(plan)


def quiet_ended_on(settings: Settings) -> date | None:
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return uow.allocation_state.quiet_ended_on()


def transactions(settings: Settings) -> list[StoredTransaction]:
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        return list(reversed(uow.transactions.list(include_voided=True)))


def system_view(settings: Settings, clock: Clock) -> SystemView:
    """Doctor sırların değerini yazmaz; yalnız tanımlı olup olmadığını (K-92)."""
    checks = bootstrap.run_doctor(settings)
    with bootstrap.open_unit_of_work(settings, readonly=True) as uow:
        runs = uow.runs.recent(since=clock.now() - timedelta(days=7))
    directory = settings.backup_dir
    backups = verify_backups(directory) if directory is not None and directory.is_dir() else []
    return SystemView(checks, runs, backups)
