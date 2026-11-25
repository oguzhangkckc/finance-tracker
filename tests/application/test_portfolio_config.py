from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.portfolio_config import ApplyReport, apply_portfolio
from finans.application.settings import effective_config
from finans.domain.models import Instrument, InstrumentKind, Side, Transaction
from finans.domain.portfolio import AlertThresholds, ConfigError, PortfolioConfig
from finans.domain.settings import SettingVersion
from finans.ports.repositories import StoredSetting

D = Decimal
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")
CONFIG = PortfolioConfig(
    instruments=(TTE, ALTIN),
    targets={"hisse": D("0.6"), "altin": D("0.4")},
    monthly_contribution=D(0),
    alerts=AlertThresholds(),
)
NOW = datetime(2026, 11, 24, tzinfo=UTC)
TODAY = date(2026, 11, 24)
JANUARY = date(2027, 1, 1)
XPP = Instrument("XPP", InstrumentKind.TEFAS_YAT, "dusuk_risk")
TOML_WARNING = "TOML'daki değer artık kullanılmıyor; geçerli ayar panelde ya da `ft ayar` ile."


def _apply(db: Path, config: PortfolioConfig) -> ApplyReport:
    with SqliteUnitOfWork(db) as uow:
        return apply_portfolio(uow, config, today=TODAY, at=NOW)


def _rows(db: Path) -> list[StoredSetting]:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        return uow.settings.list()


def test_apply_reports_changes_and_warns_when_a_held_instrument_is_deactivated(
    migrated_db: Path,
) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        report = apply_portfolio(uow, CONFIG, today=TODAY, at=NOW)
        assert report.sync.added == ("ALTIN_GR", "TTE")
        assert report.warnings == ()
        uow.transactions.add(
            Transaction("TTE", date(2026, 1, 5), Side.BUY, D("12.5"), D(10)),
            external_ref=None,
            note=None,
            created_at=NOW,
        )

    report = _apply(migrated_db, replace(CONFIG, instruments=(ALTIN,)))

    assert report.sync.deactivated == ("TTE",)
    assert report.warnings == (
        "TTE pasif yapıldı ama elde 12.5 adet var; satış girilebilir, alış girilemez.",
    )


def test_deactivating_an_instrument_without_holdings_gives_no_warning(migrated_db: Path) -> None:
    _apply(migrated_db, CONFIG)
    report = _apply(migrated_db, replace(CONFIG, instruments=(ALTIN,)))
    assert report.sync.deactivated == ("TTE",)
    assert report.warnings == ()


def test_the_first_apply_writes_the_starting_settings_and_the_next_writes_nothing(
    migrated_db: Path,
) -> None:
    first = _apply(migrated_db, CONFIG)
    second = _apply(migrated_db, CONFIG)

    assert first.settings == ("başlangıç sürümü portfolio.toml'dan yazıldı (yürürlük 0001-01-01).",)
    assert (second.settings, second.warnings) == ((), ())
    assert [(row.version, row.source, row.recorded_at) for row in _rows(migrated_db)] == [
        (SettingVersion(date.min, None, D(0), CONFIG.targets), "toml", NOW)
    ]


def test_a_changed_toml_value_is_not_used_and_only_its_name_is_shown(migrated_db: Path) -> None:
    _apply(migrated_db, CONFIG)
    changed = replace(CONFIG, monthly_contribution=D(500), payday=10)

    report = _apply(migrated_db, changed)

    assert report.warnings == (
        "portfolio.toml'daki maaş günü ve aylık katkı geçerli ayardan farklı. " + TOML_WARNING,
    )
    assert len(_rows(migrated_db)) == 1
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        in_force = effective_config(uow, changed, on=TODAY)
    assert (in_force.payday, in_force.monthly_contribution) == (None, D(0))


def test_a_class_added_to_the_toml_joins_today_and_the_planned_versions_with_zero_weight(
    migrated_db: Path,
) -> None:
    _apply(migrated_db, CONFIG)
    planned = SettingVersion(JANUARY, None, D(100), CONFIG.targets)
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.settings.add(planned, source="web", at=NOW)
    bonds = replace(
        CONFIG,
        instruments=(TTE, ALTIN, XPP),
        targets={"hisse": D("0.5"), "altin": D("0.3"), "dusuk_risk": D("0.2")},
    )

    report = _apply(migrated_db, bonds)

    zero = {"hisse": D("0.6"), "altin": D("0.4"), "dusuk_risk": D(0)}
    assert [(row.version, row.source, row.cancel_reason) for row in _rows(migrated_db)] == [
        (SettingVersion(date.min, None, D(0), CONFIG.targets), "toml", None),
        (
            planned,
            "web",
            "portfolio.toml'daki sınıf değişikliği (eklenen: dusuk_risk); aynı yürürlük günüyle"
            " yeniden yazıldı.",
        ),
        (SettingVersion(TODAY, None, D(0), zero), "toml", None),
        (SettingVersion(JANUARY, None, D(100), zero), "toml", None),
    ]
    assert report.settings == (
        "dusuk_risk sınıfı bugünden (2026-11-24) geçerli, 0 ağırlıkla eklendi.",
        "yürürlüğü 2027-01-01 olan planlanan sürüm yeni sınıf listesiyle yeniden yazıldı.",
    )
    assert report.warnings == (
        "dusuk_risk sınıfının ağırlığı 0; ağırlığını `ft ayar hedef` ya da panelden ver.",
        "portfolio.toml'daki hedefler geçerli ayardan farklı. " + TOML_WARNING,
    )


def test_a_class_with_weight_cannot_be_removed_and_nothing_is_written(migrated_db: Path) -> None:
    _apply(migrated_db, CONFIG)
    shares_only = replace(CONFIG, instruments=(TTE,), targets={"hisse": D(1)})

    with pytest.raises(ConfigError) as refused, SqliteUnitOfWork(migrated_db) as uow:
        apply_portfolio(uow, shares_only, today=TODAY, at=NOW)

    assert [str(issue) for issue in refused.value.issues] == [
        "targets.altin: portfolio.toml'dan silinmiş ama geçerli ayardaki ağırlığı 0.4. Önce"
        " ağırlığını 0 yap: sınıfı portfolio.toml'a geri ekle, `ft ayar hedef` ile 0 yap,"
        " sonra sil."
    ]
    assert len(_rows(migrated_db)) == 1
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert [stored.instrument.code for stored in uow.instruments.list()] == ["ALTIN_GR", "TTE"]


def test_a_zero_weight_class_is_removed_from_today(migrated_db: Path) -> None:
    _apply(migrated_db, CONFIG)
    with SqliteUnitOfWork(migrated_db) as uow:
        zeroed = SettingVersion(TODAY, None, D(0), {"hisse": D(1), "altin": D(0)})
        uow.settings.add(zeroed, source="cli", at=NOW)

    report = _apply(migrated_db, replace(CONFIG, instruments=(TTE,), targets={"hisse": D(1)}))

    assert _rows(migrated_db)[-1].version == SettingVersion(TODAY, None, D(0), {"hisse": D(1)})
    assert report.settings == ("altin sınıfı ayarlardan çıkarıldı (ağırlığı 0'dı).",)
    assert report.warnings == ()
