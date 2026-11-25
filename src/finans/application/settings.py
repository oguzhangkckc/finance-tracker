"""Yürürlük tarihli ayarlar (K-127). Sürüm yoksa portfolio.toml geçerlidir; ilk `config apply`
başlangıç sürümünü yazana kadar davranış değişmez. Her okuyucu ilgili günün sürümünü kullanır:
rapor mantıksal gününü, maaş günü planı maaş gününü, alarm değerlendirildiği günü."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from enum import Enum
from typing import Final

from finans.domain.models import YearMonth
from finans.domain.portfolio import PortfolioConfig
from finans.domain.settings import SettingVersion, effective_version, payday_schedule
from finans.ports.unit_of_work import UnitOfWork


class FromSettings(Enum):
    """Katkı parametresinin varsayılanı: o günün ayarı. CLI'daki --contribution üzerine yazar."""

    VALUE = "ayar"


FROM_SETTINGS: Final = FromSettings.VALUE


def active_versions(uow: UnitOfWork) -> list[SettingVersion]:
    return [stored.version for stored in uow.settings.list() if not stored.is_cancelled]


def effective_config(uow: UnitOfWork, toml: PortfolioConfig, *, on: date) -> PortfolioConfig:
    version = effective_version(active_versions(uow), on)
    if version is None:
        return toml
    return replace(
        toml,
        payday=version.payday,
        monthly_contribution=version.monthly_contribution,
        targets=dict(version.targets),
    )


def payday_for(uow: UnitOfWork, toml: PortfolioConfig) -> Callable[[YearMonth], int | None]:
    """Her ayın maaş günü o ayın 1'indeki sürümden; maaş günü işinin mantıksal günü buna göre."""
    return payday_schedule(active_versions(uow), fallback=toml.payday)
