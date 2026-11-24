import json
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal

from finans.application.portfolio_view import (
    class_values,
    instruments_by_code,
    missing_in_allocation,
)
from finans.contracts.report import AlertNotice
from finans.domain.allocation import (
    QUIET_MONTHS,
    Direction,
    DriftEvent,
    deviations,
    evaluate_portfolio_drift,
    quiet_period_over,
    should_notify,
    weights,
)
from finans.domain.models import ZERO
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.domain.valuation import PriceHistory, value_book
from finans.ports.clock import BUSINESS_TZ
from finans.ports.notifier import Notifier
from finans.ports.render import ReportRenderer
from finans.ports.repositories import AlertEvent, AlertState
from finans.ports.unit_of_work import UnitOfWork

QUIET_HOURS_START = time(23, 0)
QUIET_HOURS_END = time(8, 0)


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    evaluated: bool
    reason: str | None = None
    events: tuple[AlertEvent, ...] = ()
    quiet_ended_on: date | None = None


def is_quiet_hour(moment: datetime) -> bool:
    """23:00-08:00 arası mesajlar bildirimsiz gider (K-13)."""
    local = moment.astimezone(BUSINESS_TZ).time()
    return local >= QUIET_HOURS_START or local < QUIET_HOURS_END


def evaluate_alerts(
    uow: UnitOfWork, config: PortfolioConfig, *, on: date, now: datetime
) -> AlertEvaluation:
    """Sapma alarmları (K-45, K-46); fiyat eksikse (K-85) ya da sessiz dönemde (K-75) atlanır."""
    instruments = instruments_by_code(uow)
    transactions = [s.transaction for s in uow.transactions.list(until=on)]
    valuation = value_book(
        build_positions(transactions, as_of=on), PriceHistory(uow.prices.history(until=on)), on
    )
    missing = missing_in_allocation(valuation, instruments)
    if missing:
        return AlertEvaluation(evaluated=False, reason=f"fiyat yok: {', '.join(missing)}")
    values = class_values(valuation, instruments, config.targets)
    total = sum(values.values(), ZERO)
    if total <= ZERO:
        return AlertEvaluation(evaluated=False, reason="dağılım içi değer yok")
    ended = uow.allocation_state.quiet_ended_on()
    if not quiet_period_over(total, config.monthly_contribution, ended_on=ended):
        reason = f"sessiz dönem: dağılım içi değer {QUIET_MONTHS} aylık katkının altında"
        return AlertEvaluation(evaluated=False, reason=reason)
    if ended is None:
        uow.allocation_state.end_quiet(on)
    current = deviations(weights(values), config.targets)
    open_directions = {
        state.fingerprint.removeprefix("drift:"): state.direction
        for state in uow.alerts.list_open()
        if state.direction is not None
    }
    events: list[AlertEvent] = []
    for decision in evaluate_portfolio_drift(
        values, config.targets, open_directions, config.alerts
    ):
        deviation = current[decision.fingerprint.removeprefix("drift:")]
        for change in decision.events:
            event = AlertEvent(decision.fingerprint, change.kind, change.direction, deviation, now)
            uow.alerts.add_event(event)
            events.append(event)
        _save(uow, decision.fingerprint, decision.open_direction, decision.events, deviation, now)
    return AlertEvaluation(
        evaluated=True, events=tuple(events), quiet_ended_on=on if ended is None else None
    )


def _save(
    uow: UnitOfWork,
    fingerprint: str,
    direction: Direction | None,
    changes: tuple[DriftEvent, ...],
    deviation: Decimal,
    now: datetime,
) -> None:
    stored = uow.alerts.get(fingerprint)
    payload = json.dumps({"sapma": str(deviation)})
    if direction is not None:
        reopened = any(change.kind == "opened" for change in changes)
        if stored is None or reopened:
            uow.alerts.save(AlertState(fingerprint, direction, now, None, None, payload))
        else:
            uow.alerts.save(replace(stored, direction=direction, payload=payload))
    elif stored is not None and stored.direction is not None:
        uow.alerts.save(replace(stored, direction=None, resolved_at=now, payload=payload))


def deliver_alerts(
    uow: UnitOfWork,
    notifier: Notifier,
    renderer: ReportRenderer,
    *,
    now: datetime,
    reminder_days: int,
) -> int:
    """Bekleyen geçişleri her zaman, açık alarm hatırlatmasını `reminder_days` sonra gönderir
    (K-46). Gönderim başarısızsa hiçbir şey işaretlenmez; sonraki çalıştırma yeniden dener."""
    pending = uow.alerts.pending_events()
    notices = [
        AlertNotice(
            kind=item.event.kind,
            asset_class=item.event.fingerprint.removeprefix("drift:"),
            direction=item.event.direction,
            deviation=item.event.deviation,
            opened_at=item.event.occurred_at,
        )
        for item in pending
    ]
    touched = {item.event.fingerprint for item in pending}
    today = now.astimezone(BUSINESS_TZ).date()
    for state in uow.alerts.list_open():
        if state.direction is None or state.fingerprint in touched:
            continue
        last = state.last_notified_at
        last_day = None if last is None else last.astimezone(BUSINESS_TZ).date()
        if should_notify(last_day, today, cooldown_days=reminder_days):
            notices.append(
                AlertNotice(
                    kind="reminder",
                    asset_class=state.fingerprint.removeprefix("drift:"),
                    direction=state.direction,
                    deviation=_deviation(state.payload),
                    opened_at=state.opened_at,
                )
            )
            touched.add(state.fingerprint)
    if not notices:
        return 0
    notifier.send(renderer.alerts(notices), silent=is_quiet_hour(now))
    uow.alerts.mark_notified([item.id for item in pending], at=now)
    for fingerprint in sorted(touched):
        stored = uow.alerts.get(fingerprint)
        if stored is not None and stored.direction is not None:
            uow.alerts.save(replace(stored, last_notified_at=now))
    return len(notices)


def _deviation(payload: str) -> Decimal | None:
    data = json.loads(payload, parse_float=Decimal)
    value = data.get("sapma") if isinstance(data, dict) else None
    return Decimal(value) if isinstance(value, str) else None
