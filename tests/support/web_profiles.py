"""İki profilli web testleri: gerçek veritabanında senaryonun işlemleri var, sanal boş (K-125)."""

from datetime import UTC, datetime
from pathlib import Path

from finans import bootstrap
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.settings import Settings, profile_settings
from finans.web.app import create_app
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario
from tests.support.web_client import WebClient
from tests.web.test_pages import PORTFOLIO

LOGIN = "kisi@example.com"
ORIGIN = "https://cihaz.ornek.ts.net"
ME = {"Tailscale-User-Login": LOGIN}
# İstanbul'da Çarşamba 12:30: elle güncelleme açık.
NOW = FixedClock(datetime(2026, 11, 25, 9, 30, tzinfo=UTC))
PAGES = (
    "/",
    "/varliklar",
    "/dagilim",
    "/getiri",
    "/raporlar",
    "/raporlar/haftalik",
    "/raporlar/aylik",
    "/raporlar/maas-gunu",
    "/alarmlar",
    "/ayarlar",
    "/islemler",
    "/sistem",
    "/daha",
)


def two_profiles(tmp_path: Path, db: Path) -> Settings:
    scenario.seed(db)
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    settings = Settings(
        db_path=db,
        portfolio_path=portfolio,
        web_allowed_login=LOGIN,
        web_origin=ORIGIN,
        web_session_key="k" * 64,
    )
    sanal = profile_settings(settings)["sanal"]
    bootstrap.sanal_init(sanal, NOW)
    with SqliteUnitOfWork(sanal.db_path, sanal=True) as uow:
        uow.instruments.sync(list(scenario.CONFIG.instruments))
    return settings


def web(settings: Settings) -> WebClient:
    return WebClient(create_app(settings, clock=NOW))
