"""Sayfaların verisi: Telegram ve metin raporuyla aynı `Report` nesnesi (K-104)."""

from datetime import date

from finans import bootstrap
from finans.application.report import ReportKind, build_report
from finans.contracts.report import Report
from finans.domain.models import DomainError
from finans.ports.clock import Clock
from finans.settings import Settings

STALE_CHECK = "bayatlık"
GENERAL_STALE_CHECK = "genel bayatlık"
PAGE_ERRORS = (DomainError, bootstrap.SetupError, bootstrap.ProfileError)


class PageError(Exception):
    pass


def load_report(
    settings: Settings, clock: Clock, *, kind: ReportKind = "weekly", on: date | None = None
) -> Report:
    """Config yalnızca okunur; hedefler ve katkı oradadır (K-123 (10))."""
    if settings.portfolio_path is None:
        raise PageError("FT_PORTFOLIO_PATH tanımlı değil.")
    config = bootstrap.portfolio_source().load(settings.portfolio_path)
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
