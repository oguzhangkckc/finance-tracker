"""Rapor kontratı (K-03): metin ve JSON çıktısı aynı modelden üretilir."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# K-118: her çıktıda vardır; sanal portföy (K-107) gerçek çıktıyla karışmasın.
Profile = Literal["real", "sanal"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReturnFigure(_Model):
    """K-44: "out_of_range" kök aralık dışında, "undefined" hesaplanamadı; "missing_price"
    dağılım içi bir varlığın fiyatı yok (K-95)."""

    status: Literal["ok", "out_of_range", "undefined", "missing_price"]
    rate: Decimal | None = None
    annualized: bool | None = None


class ValueSplit(_Model):
    in_allocation: Decimal
    out_of_allocation: Decimal
    total: Decimal


class Summary(_Model):
    """`change` `change_since`ten bu yana Modified Dietz değişimi (K-94); haftalıkta 7 gün,
    aylıkta önceki ayın son gününden itibaren (K-95)."""

    values: ValueSplit
    change_since: date
    previous_total: Decimal | None
    change: Decimal | None
    simple_return: Decimal | None
    realized_pnl: Decimal
    money_weighted: ReturnFigure | None = None
    real_money_weighted: ReturnFigure | None = None
    real_same_as_nominal: bool = False


class HoldingLine(_Model):
    instrument: str
    asset_class: str
    allocation: bool
    units: Decimal
    cost: Decimal
    value: Decimal | None
    price: Decimal | None
    price_date: date | None
    source: str | None
    simple_return: Decimal | None
    real_return: Decimal | None = None


class LotLine(_Model):
    instrument: str
    acquired: date
    units: Decimal
    cost: Decimal
    value: Decimal | None
    real_return: Decimal | None
    cpi_period: str | None


class AllocationLine(_Model):
    asset_class: str
    value: Decimal
    weight: Decimal
    target: Decimal
    deviation: Decimal


class RebalanceLine(_Model):
    asset_class: str
    instrument: str
    amount: Decimal


class RebalancePlan(_Model):
    """Katkı tanımlı değilse rapordaki plan None'dır (K-56); katkı 0 ise satırsızdır (K-59)."""

    contribution: Decimal
    lines: list[RebalanceLine]


class AlertLine(_Model):
    asset_class: str
    direction: Literal["above", "below"]
    deviation: Decimal | None
    opened_at: datetime


class DataIssueLine(_Model):
    check: str
    level: Literal["warn", "info"]
    instrument: str | None
    day: date | None
    message: str


class Inflation(_Model):
    cpi_series: str
    valuation_period: str
    annual_inflation: Decimal | None


class Provenance(_Model):
    price_dates: dict[str, date]
    cpi_period: str | None
    generated_at: datetime


class SystemHealth(_Model):
    last_price_sync: datetime | None
    last_cpi_sync: datetime | None
    failed_jobs_7d: int


class Report(_Model):
    schema_version: Literal["1.0"] = "1.0"
    profile: Profile = "real"
    kind: Literal["weekly", "monthly"]
    logical_date: date
    summary: Summary
    holdings: list[HoldingLine]
    lots: list[LotLine] = Field(default_factory=list)
    allocation: list[AllocationLine]
    quiet_period: bool
    missing_prices: list[str] = Field(default_factory=list)
    allocation_skipped: list[str] = Field(default_factory=list)
    rebalance: RebalancePlan | None
    alerts: list[AlertLine]
    data_issues: list[DataIssueLine]
    inflation: Inflation | None = None
    provenance: Provenance
    health: SystemHealth


class AlertNotice(_Model):
    """Bildirilecek sapma olayı ya da açık alarm hatırlatması (K-46)."""

    kind: Literal["opened", "resolved", "reminder"]
    asset_class: str
    direction: Literal["above", "below"]
    deviation: Decimal | None
    opened_at: datetime


class PaydayLine(_Model):
    asset_class: str
    instrument: str
    amount: Decimal
    share: Decimal


class PaydayPlan(_Model):
    """Dağılım içi bir fonun fiyatı yoksa öneri yapılmaz; `missing_prices` doludur (K-95)."""

    profile: Profile = "real"
    logical_date: date
    contribution: Decimal
    lines: list[PaydayLine]
    missing_prices: list[str] = Field(default_factory=list)
