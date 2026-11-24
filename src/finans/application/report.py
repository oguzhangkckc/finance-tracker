from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from finans.application.data_check import check_data
from finans.application.portfolio_view import (
    class_values,
    in_allocation,
    instruments_by_code,
    missing_in_allocation,
)
from finans.contracts.report import (
    AlertLine,
    AllocationLine,
    DataIssueLine,
    HoldingLine,
    Inflation,
    LotLine,
    PaydayLine,
    PaydayPlan,
    Profile,
    Provenance,
    RebalanceLine,
    RebalancePlan,
    Report,
    ReturnFigure,
    Summary,
    SystemHealth,
    ValueSplit,
)
from finans.domain.allocation import deviations, plan_contribution, quiet_threshold, weights
from finans.domain.inflation import CpiSeries, annual_inflation, reference_period
from finans.domain.models import ZERO, DomainError, Instrument, Transaction
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import PositionBook, build_positions
from finans.domain.returns import (
    PeriodReturn,
    Unavailable,
    lot_real_return,
    modified_dietz,
    money_weighted_return,
    portfolio_cash_flows,
    real_cash_flows,
    real_simple_return,
    simple_return,
)
from finans.domain.valuation import PriceHistory, Valuation, value_book
from finans.ports.unit_of_work import UnitOfWork

ReportKind = Literal["weekly", "monthly"]
WEEK = timedelta(days=7)
DAY = timedelta(days=1)


def build_report(
    uow: UnitOfWork,
    config: PortfolioConfig,
    *,
    kind: ReportKind,
    logical_date: date,
    contribution: Decimal | None,
    now: datetime,
    cpi_series: str,
    profile: Profile = "real",
) -> Report:
    """`contribution` bu ayki katkıdır: config ya da --contribution; None ise tanımlı değil.

    Fiyatı olmayan varlık değerlenmez; dağılım içinde böyle bir varlık varsa dağılım, katkı
    planı ve para ağırlıklı getiri hesaplanmaz (K-85, K-95).
    """
    instruments = instruments_by_code(uow)
    transactions = [s.transaction for s in uow.transactions.list(until=logical_date)]
    history = PriceHistory(uow.prices.history(until=logical_date))
    book = build_positions(transactions, as_of=logical_date)
    valuation = value_book(book, history, logical_date)
    points = uow.cpi.points(cpi_series)
    series = CpiSeries(points) if points and kind == "monthly" else None
    missing = sorted(valuation.missing_prices)
    skipped = missing_in_allocation(valuation, instruments)

    split = _split(valuation, instruments)
    allocation = (
        []
        if skipped
        else _allocation(class_values(valuation, instruments, config.targets), config.targets)
    )
    current = {line.asset_class: line.deviation for line in allocation}
    since = logical_date - WEEK if kind == "weekly" else logical_date.replace(day=1) - DAY
    summary = Summary(
        values=split,
        change_since=since,
        previous_total=None,
        change=None,
        simple_return=None
        if missing
        else simple_return(valuation.total_value, valuation.priced_cost),
        realized_pnl=book.realized_pnl(),
    )
    if not missing:
        summary = _with_change(summary, transactions, history, since, logical_date, split.total)
    if kind == "monthly":
        summary = _with_money_weighted(
            summary, transactions, instruments, split, series, logical_date, skipped
        )
    return Report(
        profile=profile,
        kind=kind,
        logical_date=logical_date,
        summary=summary,
        holdings=_holdings(valuation, instruments, book, series, logical_date),
        lots=_lots(book, history, series, logical_date) if kind == "monthly" else [],
        allocation=allocation,
        quiet_period=uow.allocation_state.quiet_ended_on() is None
        and quiet_threshold(config.monthly_contribution) > ZERO,
        missing_prices=missing,
        allocation_skipped=skipped,
        rebalance=_rebalance(valuation, instruments, config, contribution)
        if kind == "monthly" and not skipped
        else None,
        alerts=[
            AlertLine(
                asset_class=state.fingerprint.removeprefix("drift:"),
                direction=state.direction,
                deviation=current.get(state.fingerprint.removeprefix("drift:")),
                opened_at=state.opened_at,
            )
            for state in uow.alerts.list_open()
            if state.direction is not None
        ],
        data_issues=_data_issues(uow, config, since, logical_date),
        inflation=_inflation(series, cpi_series, logical_date),
        provenance=Provenance(
            price_dates={
                h.instrument: h.price.price_date for h in valuation.holdings if h.price is not None
            },
            cpi_period=None if series is None else str(reference_period(logical_date, series)),
            generated_at=now,
        ),
        health=SystemHealth(
            last_price_sync=uow.prices.last_fetched_at(),
            last_cpi_sync=uow.cpi.last_fetched_at(cpi_series),
            failed_jobs_7d=sum(
                1 for run in uow.runs.recent(since=now - WEEK) if run.status == "failed"
            ),
        ),
    )


def payday_plan(
    uow: UnitOfWork,
    config: PortfolioConfig,
    *,
    on: date,
    contribution: Decimal | None,
    profile: Profile = "real",
) -> PaydayPlan:
    """Maaş günü mesajı: katkının sınıf ve fon bazında dağılımı (K-83)."""
    if contribution is None:
        raise DomainError("Katkı tanımlı değil; [contribution] altında monthly gerekli.")
    instruments = instruments_by_code(uow)
    transactions = [s.transaction for s in uow.transactions.list(until=on)]
    valuation = value_book(
        build_positions(transactions, as_of=on), PriceHistory(uow.prices.history(until=on)), on
    )
    skipped = [
        code for code in sorted(valuation.missing_prices) if in_allocation(code, instruments)
    ]
    if skipped:
        return PaydayPlan(
            profile=profile,
            logical_date=on,
            contribution=contribution,
            lines=[],
            missing_prices=skipped,
        )
    funds = _funds(valuation, instruments, config.targets)
    return PaydayPlan(
        profile=profile,
        logical_date=on,
        contribution=contribution,
        lines=[
            PaydayLine(
                asset_class=line.asset_class,
                instrument=line.instrument,
                amount=line.amount,
                share=line.amount / contribution if contribution > ZERO else ZERO,
            )
            for line in plan_contribution(funds, config.targets, contribution)
        ],
    )


def _split(valuation: Valuation, instruments: Mapping[str, Instrument]) -> ValueSplit:
    inside = sum(
        (
            h.value
            for h in valuation.holdings
            if h.value is not None and in_allocation(h.instrument, instruments)
        ),
        ZERO,
    )
    return ValueSplit(
        in_allocation=inside,
        out_of_allocation=valuation.total_value - inside,
        total=valuation.total_value,
    )


def _with_change(
    summary: Summary,
    transactions: Sequence[Transaction],
    history: PriceHistory,
    since: date,
    on: date,
    total: Decimal,
) -> Summary:
    previous = value_book(build_positions(transactions, as_of=since), history, since)
    if not previous.holdings or previous.missing_prices:
        return summary
    flows = [tx.cash_flow() for tx in transactions if since < tx.trade_date <= on]
    return summary.model_copy(
        update={
            "previous_total": previous.total_value,
            "change": modified_dietz(
                previous.total_value, total, flows, start_day=since, end_day=on
            ),
        }
    )


def _allocation(
    class_values: Mapping[str, Decimal], targets: Mapping[str, Decimal]
) -> list[AllocationLine]:
    if sum(class_values.values(), ZERO) <= ZERO:
        return []
    current = weights(class_values)
    gaps = deviations(current, targets)
    return [
        AllocationLine(
            asset_class=name,
            value=class_values[name],
            weight=current[name],
            target=targets[name],
            deviation=gaps[name],
        )
        for name in sorted(targets)
    ]


def _funds(
    valuation: Valuation, instruments: Mapping[str, Instrument], targets: Mapping[str, Decimal]
) -> dict[str, dict[str, Decimal]]:
    """Dağılım içi etkin fonlar ve değerleri; payı olmayan fonun değeri 0'dır."""
    values = {h.instrument: h.value for h in valuation.holdings if h.value is not None}
    funds: dict[str, dict[str, Decimal]] = {name: {} for name in targets}
    for code, instrument in instruments.items():
        if instrument.allocation and instrument.asset_class in funds:
            funds[instrument.asset_class][code] = values.get(code, ZERO)
    return funds


def _rebalance(
    valuation: Valuation,
    instruments: Mapping[str, Instrument],
    config: PortfolioConfig,
    contribution: Decimal | None,
) -> RebalancePlan | None:
    if contribution is None:
        return None
    if contribution == ZERO:
        return RebalancePlan(contribution=contribution, lines=[])
    lines = plan_contribution(
        _funds(valuation, instruments, config.targets), config.targets, contribution
    )
    return RebalancePlan(
        contribution=contribution,
        lines=[
            RebalanceLine(
                asset_class=line.asset_class, instrument=line.instrument, amount=line.amount
            )
            for line in lines
        ],
    )


def _holdings(
    valuation: Valuation,
    instruments: Mapping[str, Instrument],
    book: PositionBook,
    series: CpiSeries | None,
    on: date,
) -> list[HoldingLine]:
    lines = []
    for holding in sorted(valuation.holdings, key=lambda h: h.instrument):
        instrument = instruments.get(holding.instrument)
        inside = in_allocation(holding.instrument, instruments)
        real = None
        if not inside and series is not None and holding.value is not None:
            real = real_simple_return(
                book.lots_of(holding.instrument), holding.value, series, on=on
            )
        lines.append(
            HoldingLine(
                instrument=holding.instrument,
                asset_class="" if instrument is None else instrument.asset_class,
                allocation=inside,
                units=holding.units,
                cost=holding.cost,
                value=holding.value,
                price=None if holding.price is None else holding.price.price,
                price_date=None if holding.price is None else holding.price.price_date,
                source=None if holding.price is None else holding.price.source,
                simple_return=None
                if holding.value is None
                else simple_return(holding.value, holding.cost),
                real_return=real,
            )
        )
    return lines


def _lots(
    book: PositionBook, history: PriceHistory, series: CpiSeries | None, on: date
) -> list[LotLine]:
    lines = []
    for lot in sorted(book.lots, key=lambda lot: (lot.instrument, lot.acquired)):
        price = history.as_of(lot.instrument, on)
        value = None if price is None else lot.units * price.price
        real = None
        if value is not None and series is not None and lot.cost > ZERO:
            real = lot_real_return(lot, value, series, on=on)
        lines.append(
            LotLine(
                instrument=lot.instrument,
                acquired=lot.acquired,
                units=lot.units,
                cost=lot.cost,
                value=value,
                real_return=real,
                cpi_period=None if series is None else str(reference_period(lot.acquired, series)),
            )
        )
    return lines


def _figure(result: PeriodReturn | Unavailable) -> ReturnFigure:
    if isinstance(result, Unavailable):
        return ReturnFigure(status=result.reason)
    return ReturnFigure(status="ok", rate=result.rate, annualized=result.annualized)


def _with_money_weighted(
    summary: Summary,
    transactions: Sequence[Transaction],
    instruments: Mapping[str, Instrument],
    split: ValueSplit,
    series: CpiSeries | None,
    on: date,
    skipped: Sequence[str],
) -> Summary:
    """Para ağırlıklı getiri yalnızca dağılım içi portföy için (K-74)."""
    if skipped:
        missing = ReturnFigure(status="missing_price")
        return summary.model_copy(
            update={"money_weighted": missing, "real_money_weighted": missing}
        )
    inside = [tx for tx in transactions if in_allocation(tx.instrument, instruments)]
    flows = portfolio_cash_flows(inside, terminal_value=split.in_allocation, on=on)
    if series is None:
        return summary.model_copy(update={"money_weighted": _figure(money_weighted_return(flows))})
    valuation_period = reference_period(on, series)
    return summary.model_copy(
        update={
            "money_weighted": _figure(money_weighted_return(flows)),
            "real_money_weighted": _figure(
                money_weighted_return(real_cash_flows(flows, series, on=on))
            ),
            "real_same_as_nominal": bool(inside)
            and all(reference_period(tx.trade_date, series) == valuation_period for tx in inside),
        }
    )


def _inflation(series: CpiSeries | None, cpi_series: str, on: date) -> Inflation | None:
    if series is None:
        return None
    period = reference_period(on, series)
    return Inflation(
        cpi_series=cpi_series,
        valuation_period=str(period),
        annual_inflation=annual_inflation(series, period)
        if period.shift(-12) in series.periods()
        else None,
    )


def _data_issues(
    uow: UnitOfWork, config: PortfolioConfig, since: date, on: date
) -> list[DataIssueLine]:
    return [
        DataIssueLine(
            check=issue.check,
            level=issue.level,
            instrument=issue.instrument,
            day=issue.day,
            message=issue.message,
        )
        for issue in check_data(uow, quality=config.quality, today=on, since=since)
    ]
