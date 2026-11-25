from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.render.text import TextRenderer
from finans.adapters.sqlite import connection as sqlite_connection
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.alerts import AlertEvaluation, deliver_alerts, evaluate_alerts
from finans.domain.models import PricePoint
from finans.domain.portfolio import PortfolioConfig
from finans.ports.notifier import NotifyError
from finans.ports.unit_of_work import UnitOfWork
from tests.fakes.notifier import FakeNotifier
from tests.support import report_scenario as scenario

D = Decimal
SUNDAY = date(2026, 11, 29)
EVENING = datetime(2026, 11, 29, 17, 0, tzinfo=UTC)
NIGHT = datetime(2026, 11, 29, 20, 30, tzinfo=UTC)
RENDERER = TextRenderer(html=True)
# Ağırlıklar hisse %55,6 ve dusuk_risk %44,4; hedefler alarm açacak kadar uzak.
APART = replace(
    scenario.CONFIG,
    targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")},
    monthly_contribution=None,
)


def _evaluate(db: Path, config: PortfolioConfig, now: datetime = EVENING) -> AlertEvaluation:
    with SqliteUnitOfWork(db) as uow:
        return evaluate_alerts(uow, config, on=SUNDAY, now=now)


def _opener(db: Path) -> Callable[[], UnitOfWork]:
    return lambda: SqliteUnitOfWork(db)


def _kinds(result: AlertEvaluation) -> list[tuple[str, str, str]]:
    return [(e.fingerprint, e.kind, e.direction) for e in result.events]


def test_missing_price_skips_the_evaluation(migrated_db: Path) -> None:
    scenario.seed(migrated_db, priced=("XHT", "XAC"))

    result = _evaluate(migrated_db, APART)

    assert result == AlertEvaluation(evaluated=False, reason="fiyat yok: XPP")
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert uow.alerts.list_open() == []
        assert uow.allocation_state.quiet_ended_on() is None


def test_quiet_period_ends_once_at_the_threshold_and_never_returns(migrated_db: Path) -> None:
    scenario.seed(migrated_db)
    below = replace(APART, monthly_contribution=D(1000))
    above = replace(APART, monthly_contribution=D(700))

    assert _evaluate(migrated_db, below) == AlertEvaluation(
        evaluated=False, reason="sessiz dönem: dağılım içi değer 3 aylık katkının altında"
    )
    opened = _evaluate(migrated_db, above)
    assert (opened.evaluated, opened.quiet_ended_on) == (True, SUNDAY)
    again = _evaluate(migrated_db, below)
    assert (again.evaluated, again.quiet_ended_on) == (True, None)
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert uow.allocation_state.quiet_ended_on() == SUNDAY


def test_alarm_opens_once_and_closes_only_below_the_lower_threshold(migrated_db: Path) -> None:
    scenario.seed(migrated_db)

    assert _kinds(_evaluate(migrated_db, APART)) == [
        ("drift:dusuk_risk", "opened", "above"),
        ("drift:hisse", "opened", "below"),
    ]
    assert _evaluate(migrated_db, APART).events == ()
    near = replace(APART, targets={"hisse": D("0.6"), "dusuk_risk": D("0.4")})
    assert _evaluate(migrated_db, near).events == ()
    close = replace(APART, targets={"hisse": D("0.56"), "dusuk_risk": D("0.44")})
    assert _kinds(_evaluate(migrated_db, close)) == [
        ("drift:dusuk_risk", "resolved", "above"),
        ("drift:hisse", "resolved", "below"),
    ]
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert uow.alerts.list_open() == []


def test_sign_flip_closes_and_reopens_in_order(migrated_db: Path) -> None:
    scenario.seed(migrated_db)
    _evaluate(migrated_db, APART)
    flipped = replace(APART, targets={"hisse": D("0.45"), "dusuk_risk": D("0.55")})

    assert _kinds(_evaluate(migrated_db, flipped)) == [
        ("drift:dusuk_risk", "resolved", "above"),
        ("drift:dusuk_risk", "opened", "below"),
        ("drift:hisse", "resolved", "below"),
        ("drift:hisse", "opened", "above"),
    ]


def test_pending_transitions_go_in_one_message_silently_at_night(migrated_db: Path) -> None:
    scenario.seed(migrated_db)
    _evaluate(migrated_db, APART)
    notifier = FakeNotifier()

    sent = deliver_alerts(_opener(migrated_db), notifier, RENDERER, now=NIGHT, reminder_days=7)

    assert sent == 2
    [(text, silent)] = notifier.sent
    assert silent
    assert "dusuk_risk: hedefin üstüne çıktı, sapma +14,4 puan" in text
    assert "hisse: hedefin altına düştü, sapma -14,4 puan" in text
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert uow.alerts.pending_events() == []
        assert {state.last_notified_at for state in uow.alerts.list_open()} == {NIGHT}


def test_failed_send_leaves_transitions_pending(migrated_db: Path) -> None:
    scenario.seed(migrated_db)
    _evaluate(migrated_db, APART)

    with pytest.raises(NotifyError):
        deliver_alerts(
            _opener(migrated_db), FakeNotifier(fail=True), RENDERER, now=EVENING, reminder_days=7
        )

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert len(uow.alerts.pending_events()) == 2


def test_open_alarm_is_reminded_after_the_cooldown(migrated_db: Path) -> None:
    scenario.seed(migrated_db)
    _evaluate(migrated_db, APART)
    deliver_alerts(_opener(migrated_db), FakeNotifier(), RENDERER, now=EVENING, reminder_days=7)
    notifier = FakeNotifier()

    for days in (3, 7):
        later = EVENING + timedelta(days=days)
        deliver_alerts(_opener(migrated_db), notifier, RENDERER, now=later, reminder_days=7)

    [(text, silent)] = notifier.sent
    assert not silent
    assert "Hatırlatma: hisse hâlâ hedefin altında, sapma -14,4 puan" in text


@dataclass
class SlowNotifier:
    """Telegram yanıtı gecikirken başka bir süreç (ör. web) veritabanına yazar."""

    db: Path
    sent: list[str] = field(default_factory=list)

    def send(self, text: str, *, silent: bool) -> None:
        with SqliteUnitOfWork(self.db) as uow:
            point = PricePoint("XHT", SUNDAY, D("12.000000"), "tefas")
            uow.prices.upsert(point, fetched_at=EVENING)
        self.sent.append(text)


def test_a_slow_telegram_send_holds_no_database_lock(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K-131: olay yazılır ve işlem kapanır; gönderim işlem dışında, işaretleme ayrı ve kısa."""
    monkeypatch.setattr(sqlite_connection, "BUSY_TIMEOUT_MS", 50)
    scenario.seed(migrated_db)
    _evaluate(migrated_db, APART)
    notifier = SlowNotifier(migrated_db)

    sent = deliver_alerts(_opener(migrated_db), notifier, RENDERER, now=EVENING, reminder_days=7)

    assert sent == 2
    assert len(notifier.sent) == 1
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert uow.prices.on("XHT", SUNDAY) is not None
        assert uow.alerts.pending_events() == []


def test_a_failed_send_is_retried_on_the_next_run_and_then_never_repeated(
    migrated_db: Path,
) -> None:
    scenario.seed(migrated_db)
    _evaluate(migrated_db, APART)
    notifier = FakeNotifier()
    later = EVENING + timedelta(hours=1)

    with pytest.raises(NotifyError):
        deliver_alerts(
            _opener(migrated_db), FakeNotifier(fail=True), RENDERER, now=EVENING, reminder_days=7
        )
    retried = deliver_alerts(_opener(migrated_db), notifier, RENDERER, now=later, reminder_days=7)
    again = deliver_alerts(_opener(migrated_db), notifier, RENDERER, now=later, reminder_days=7)

    assert (retried, again) == (2, 0)
    assert len(notifier.sent) == 1
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert {state.last_notified_at for state in uow.alerts.list_open()} == {later}
