"""İki profilli API testleri: gerçek veritabanında senaryonun işlemleri var, sanal boş (K-125)."""

from datetime import UTC, datetime
from pathlib import Path

from finans import bootstrap
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.settings import Settings, profile_settings
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario

ORIGIN = "https://finans.ornek.com"
# İstanbul'da Çarşamba 12:30: elle güncelleme açık.
NOW = FixedClock(datetime(2026, 11, 25, 9, 30, tzinfo=UTC))
PORTFOLIO = """
[targets]
hisse = 0.6
dusuk_risk = 0.4

[sinif_adlari]
dusuk_risk = "Düşük risk"

[contribution]
monthly = 1000
payday = 15

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse"

[[instruments]]
code = "XPP"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"
category = "para_piyasasi"

[[instruments]]
code = "XAC"
kind = "TEFAS_YAT"
asset_class = "acil_durum"
allocation = false
"""


def two_profiles(tmp_path: Path, db: Path) -> Settings:
    scenario.seed(db)
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    settings = Settings(
        db_path=db,
        portfolio_path=portfolio,
        web_origin=ORIGIN,
        web_session_key="k" * 64,
    )
    sanal = profile_settings(settings)["sanal"]
    bootstrap.sanal_init(sanal, NOW)
    with SqliteUnitOfWork(sanal.db_path, sanal=True) as uow:
        uow.instruments.sync(list(scenario.CONFIG.instruments))
    return settings
