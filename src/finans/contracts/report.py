"""Rapor kontratı (K-03): metin ve JSON çıktısı aynı modelden üretilir."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReturnFigure(_Model):
    """K-44: "out_of_range" kök aralık dışında, "undefined" hesaplanamadı."""

    status: Literal["ok", "out_of_range", "undefined"]
    rate: Decimal | None = None
    annualized: bool | None = None


class ValueSplit(_Model):
    in_allocation: Decimal
    out_of_allocation: Decimal
    total: Decimal


class Summary(_Model):
    values: ValueSplit
    previous_total: Decimal | None
    weekly_change: Decimal | None
    simple_return: Decimal | None
    realized_pnl: Decimal
    money_weighted: ReturnFigure | None = None
    real_money_weighted: ReturnFigure | None = None


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
    kind: Literal["weekly", "monthly"]
    logical_date: date
    summary: Summary
    holdings: list[HoldingLine]
    lots: list[LotLine] = Field(default_factory=list)
    allocation: list[AllocationLine]
    quiet_period: bool
    rebalance: RebalancePlan | None
    alerts: list[AlertLine]
    data_issues: list[DataIssueLine]
    inflation: Inflation | None = None
    provenance: Provenance
    health: SystemHealth


class PaydayLine(_Model):
    asset_class: str
    instrument: str
    amount: Decimal
    share: Decimal


class PaydayPlan(_Model):
    logical_date: date
    contribution: Decimal
    lines: list[PaydayLine]
