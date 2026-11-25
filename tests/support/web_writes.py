"""Yazma testleri için iki profilli site, oturum ve CLI eşlik yardımcıları (K-126)."""

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.password import hash_password
from finans.cli.main import app as ft_app
from finans.domain.models import PricePoint
from finans.ports.repositories import StoredTransaction
from finans.settings import Profile, Settings, profile_settings
from finans.web.app import create_app
from tests.fakes.clock import FixedClock
from tests.support import report_scenario as scenario
from tests.support.web_browser import Browser, hidden_fields
from tests.support.web_client import WebClient
from tests.support.web_profiles import two_profiles

PASSWORD = "uzun bir parola cümlesi"  # noqa: S105 - sahte test değeri
STORED = hash_password(PASSWORD)
# İstanbul'da Çarşamba 12:30; senaryonun 25 Kasım fiyatları kayıtlı, XHT'de 110 pay var.
NOW = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)
GERCEK = "<strong>GERÇEK</strong> portföye kaydedilecek."
SANAL = "<strong>SANAL</strong> portföye kaydedilecek."
REAL_BUY = {
    "fon": "XHT",
    "gun": "2026-11-25",
    "adet": "10",
    "fiyat": "11,000000",
    "komisyon": "0",
    "dekont": "D-1",
}
SLUG: dict[Profile, str] = {"real": "gercek", "sanal": "sanal"}


@dataclass
class Site:
    settings: Settings
    clock: FixedClock
    client: WebClient

    def conf(self, profile: Profile) -> Settings:
        return profile_settings(self.settings)[profile]

    def rows(self, profile: Profile) -> list[StoredTransaction]:
        conf = self.conf(profile)
        with SqliteUnitOfWork(conf.db_path, readonly=True, sanal=profile == "sanal") as uow:
            return uow.transactions.list(include_voided=True)

    def browser(self, *, unlocked: bool = True) -> Browser:
        me = Browser(self.client)
        if unlocked:
            assert me.unlock(PASSWORD).status_code == 303
        return me


def priced_sanal(sanal: Settings) -> None:
    with SqliteUnitOfWork(sanal.db_path, sanal=True) as uow:
        for day, prices in scenario.PRICES.items():
            for code, price in prices.items():
                point = PricePoint(code, day, Decimal(price), "tefas")
                uow.prices.upsert(point, fetched_at=scenario.PRICE_FETCH)


def make_site(tmp_path: Path, db: Path, *, stored: str | None = STORED) -> Site:
    settings = two_profiles(tmp_path, db)
    if stored is not None:
        settings = settings.model_copy(update={"web_password": SecretStr(stored)})
    priced_sanal(profile_settings(settings)["sanal"])
    clock = FixedClock(NOW)
    return Site(settings, clock, WebClient(create_app(settings, clock=clock)))


def post_preview(me: Browser, profile: Profile, kind: str, data: dict[str, str]) -> httpx.Response:
    return me.post(f"/{SLUG[profile]}/islemler/yeni/{kind}", data)


def post_confirm(me: Browser, profile: Profile, preview: httpx.Response) -> httpx.Response:
    action = f"/{SLUG[profile]}/islemler/kaydet"
    return me.post(action, hidden_fields(preview.text, action))


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
