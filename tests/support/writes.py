"""Yazma testleri için fiyatlı sanal profil, ayar başlangıcı ve CLI eşlik yardımcıları (K-126)."""

from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans import bootstrap
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.cli.main import app as ft_app
from finans.domain.models import PricePoint
from finans.domain.settings import start_version
from finans.ports.repositories import StoredTransaction
from finans.settings import Profile, Settings, profile_settings
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario
from tests.support.profiles import two_profiles

# İstanbul'da Çarşamba 12:30; senaryonun 25 Kasım fiyatları kayıtlı, XHT'de 110 pay var.
NOW = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)


def priced_sanal(sanal: Settings) -> None:
    with SqliteUnitOfWork(sanal.db_path, sanal=True) as uow:
        for day, prices in scenario.PRICES.items():
            for code, price in prices.items():
                point = PricePoint(code, day, Decimal(price), "tefas")
                uow.prices.upsert(point, fetched_at=scenario.PRICE_FETCH)


def same_row(stored: StoredTransaction) -> tuple[object, ...]:
    """Ondalıkların girilen basamakları da aynı olmalı (K-64)."""
    tx = stored.transaction
    scales = tuple(value.as_tuple() for value in (tx.units, tx.unit_price, tx.fee))
    return (tx, scales, stored.external_ref, stored.note, stored.voided_at)


def cli_twin(tmp_path: Path) -> Settings:
    """Aynı senaryoyla kurulmuş ikinci bir veritabanı; CLI eşlik testi oraya yazar."""
    db = tmp_path / "cli" / "finans.db"
    db.parent.mkdir()
    with closing(connect(db)) as conn:
        apply(conn, bundled(), clock=FixedClock(NOW))
    settings = two_profiles(db.parent, db)
    priced_sanal(profile_settings(settings)["sanal"])
    return settings


def run_cli(settings: Settings, profile: Profile, args: list[str], mp: pytest.MonkeyPatch) -> None:
    mp.setenv("FT_DB_PATH", str(settings.db_path))
    mp.setenv("FT_SANAL_DB_PATH", str(settings.sanal_database))
    mp.setenv("FT_PROFILE", profile)
    result = CliRunner().invoke(ft_app, args)
    assert result.exit_code == 0, result.output


def cli_rows(settings: Settings, profile: Profile) -> list[StoredTransaction]:
    conf = profile_settings(settings)[profile]
    with SqliteUnitOfWork(conf.db_path, readonly=True, sanal=profile == "sanal") as uow:
        return uow.transactions.list(include_voided=True)


def start_settings(settings: Settings) -> None:
    """İki profile de ilk `config apply`'ın yazacağı ayar başlangıç sürümü (K-127)."""
    assert settings.portfolio_path is not None
    start = start_version(bootstrap.portfolio_source().load(settings.portfolio_path))
    for profile, conf in profile_settings(settings).items():
        with SqliteUnitOfWork(conf.db_path, sanal=profile == "sanal") as uow:
            uow.settings.add(start, source="toml", at=NOW)
