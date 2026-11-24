import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.render.text import TextRenderer
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.backup import BackupOutcome
from finans.application.jobs import (
    JobContext,
    JobError,
    JobOutcome,
    JobResult,
    job_body,
    run_job,
)
from finans.domain.models import CpiPoint, YearMonth
from finans.domain.portfolio import PortfolioConfig
from finans.ports.operations import HealthPing, JobLock
from finans.ports.sources import FetchResult, RawPayload
from tests.fakes.clock import FixedClock
from tests.fakes.notifier import FakeNotifier
from tests.fakes.operations import FakeLock, FakePing
from tests.fakes.sources import FakeCpiSource, FakePriceSource
from tests.support import report_scenario as scenario

D = Decimal
FRIDAY = date(2026, 11, 27)
SUNDAY = date(2026, 11, 29)
MONTH_END = date(2026, 11, 30)
APART = replace(
    scenario.CONFIG,
    targets={"hisse": D("0.7"), "dusuk_risk": D("0.3")},
    monthly_contribution=None,
)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 11, 27, 18, 31, tzinfo=UTC))


def _context(
    db: Path,
    clock: FixedClock,
    *,
    notifier: FakeNotifier | None = None,
    cpi: FakeCpiSource | None = None,
    config: PortfolioConfig = scenario.CONFIG,
    weekly: bool = False,
) -> JobContext:
    return JobContext(
        config=config,
        open_uow=lambda: SqliteUnitOfWork(db),
        clock=clock,
        cpi_series=scenario.SERIES,
        cpi_base="2025=100",
        price_source=lambda: nullcontext(FakePriceSource()),
        cpi_source=lambda: nullcontext(cpi or FakeCpiSource(FetchResult([], []))),
        notifier=None if notifier is None else (lambda: nullcontext(notifier)),
        renderer=TextRenderer(hide_amounts=True, payday_amounts=False, html=True),
        weekly_enabled=weekly,
    )


def _run(
    db: Path,
    job: str,
    day: date,
    body: Callable[[], JobResult],
    clock: FixedClock,
    *,
    lock: JobLock | None = None,
    ping: HealthPing | None = None,
    secrets: tuple[str, ...] = (),
) -> JobOutcome:
    return run_job(
        job,
        day,
        body,
        open_uow=lambda: SqliteUnitOfWork(db),
        lock=lock or FakeLock(),
        clock=clock,
        ping=ping,
        secrets=secrets,
    )


def _runs(db: Path) -> list[tuple[str, str, object]]:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        runs = uow.runs.recent(since=datetime(2000, 1, 1, tzinfo=UTC))
    return [(run.job, run.status, json.loads(run.detail or "{}")) for run in runs]


def test_ok_run_is_recorded_pinged_and_the_same_day_is_skipped(
    migrated_db: Path, clock: FixedClock
) -> None:
    calls: list[int] = []
    ping = FakePing()

    def body() -> JobResult:
        calls.append(1)
        return JobResult("ok", {"gönderim": "gönderildi"})

    first = _run(migrated_db, "weekly-report", SUNDAY, body, clock, ping=ping)
    second = _run(migrated_db, "weekly-report", SUNDAY, body, clock, ping=ping)

    assert (first.status, second.status, len(calls)) == ("ok", "skipped", 1)
    assert _runs(migrated_db) == [("weekly-report", "ok", {"gönderim": "gönderildi"})]
    assert ping.pings == [("reports", True)]


def test_failure_is_recorded_with_secrets_masked_and_can_be_retried(
    migrated_db: Path, clock: FixedClock
) -> None:
    ping = FakePing()

    def broken() -> JobResult:
        raise RuntimeError("gizli-123 ile bot42:XYZ reddedildi")

    failed = _run(
        migrated_db, "monthly-report", MONTH_END, broken, clock, ping=ping, secrets=("gizli-123",)
    )
    retried = _run(migrated_db, "monthly-report", MONTH_END, lambda: JobResult("ok", {}), clock)

    assert failed.detail == {"hata": "RuntimeError: *** ile bot*** reddedildi"}
    assert (failed.status, retried.status) == ("failed", "ok")
    assert ping.pings == [("reports", False)]


def test_busy_lock_runs_nothing_and_partial_sends_no_ping(
    migrated_db: Path, clock: FixedClock
) -> None:
    ping = FakePing()
    busy = _run(
        migrated_db, "backup", SUNDAY, lambda: JobResult("ok", {}), clock, lock=FakeLock(busy=True)
    )
    assert busy.status == "busy"
    assert _runs(migrated_db) == []

    waiting = _run(
        migrated_db, "monthly-report", MONTH_END, lambda: JobResult("partial", {}), clock, ping=ping
    )
    assert (waiting.status, ping.pings) == ("partial", [])


def test_stale_running_attempt_is_taken_over(migrated_db: Path, clock: FixedClock) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.runs.start("sync-prices", FRIDAY, at=clock.now())

    _run(migrated_db, "sync-prices", FRIDAY, lambda: JobResult("ok", {}), clock)

    assert _runs(migrated_db) == [
        ("sync-prices", "failed", {"hata": "önceki deneme yarıda kaldı; devralındı"}),
        ("sync-prices", "ok", {}),
    ]


def test_ping_problem_is_noted_without_changing_the_outcome(
    migrated_db: Path, clock: FixedClock
) -> None:
    outcome = _run(
        migrated_db, "backup", SUNDAY, lambda: JobResult("ok", {}), clock, ping=FakePing(fail=True)
    )
    assert outcome.status == "ok"
    assert str(outcome.detail["ping"]).startswith("gönderilemedi")


def test_price_sync_evaluates_and_delivers_alerts_when_complete(
    migrated_db: Path, clock: FixedClock
) -> None:
    scenario.seed(migrated_db)
    notifier = FakeNotifier()
    context = _context(migrated_db, clock, notifier=notifier, config=APART)

    result = job_body("sync-prices", FRIDAY, context)()

    assert result.status == "ok"
    assert (result.detail["alarm"], result.detail["bildirim"]) == ("değerlendirildi, 2 olay", 2)
    assert len(notifier.sent) == 1


def test_price_sync_with_a_missing_price_skips_alerts(migrated_db: Path, clock: FixedClock) -> None:
    scenario.seed(migrated_db, priced=("XHT", "XAC"))
    notifier = FakeNotifier()
    context = _context(migrated_db, clock, notifier=notifier, config=APART)

    result = job_body("sync-prices", FRIDAY, context)()

    assert result.status == "partial"
    assert (result.detail["eksik"], result.detail["alarm"]) == (["XPP"], "atlandı: fiyat eksik")
    assert notifier.sent == []


def test_weekly_report_is_sent_only_when_enabled(migrated_db: Path, clock: FixedClock) -> None:
    scenario.seed(migrated_db)
    notifier = FakeNotifier()

    off = job_body("weekly-report", SUNDAY, _context(migrated_db, clock, notifier=notifier))()
    on = job_body(
        "weekly-report", SUNDAY, _context(migrated_db, clock, notifier=notifier, weekly=True)
    )()

    assert off.detail == {"gönderim": "haftalık rapor kapalı (FT_WEEKLY_REPORT_ENABLED)"}
    assert on.status == "ok"
    [(text, silent)] = notifier.sent
    assert text.startswith("Haftalık rapor (2026-11-29)")
    assert "TL" not in text
    assert not silent


def test_monthly_report_waits_for_cpi_until_the_tenth(migrated_db: Path) -> None:
    scenario.seed(migrated_db)
    notifier = FakeNotifier()

    def monthly(day: int) -> JobResult:
        clock = FixedClock(datetime(2026, 12, day, 8, 0, tzinfo=UTC))
        context = _context(migrated_db, clock, notifier=notifier)
        return job_body("monthly-report", MONTH_END, context)()

    early = monthly(6)
    assert (early.status, early.detail) == ("partial", {"gönderim": "2026-11 TÜFE'si bekleniyor"})
    assert notifier.sent == []

    late = monthly(10)
    assert late.status == "ok"
    assert notifier.sent[0][0].startswith(
        "Not: 2026-11 TÜFE'si henüz yok; en son dönemle hesaplandı.\n\nAylık rapor (2026-11-30)"
    )

    with SqliteUnitOfWork(migrated_db) as uow:
        uow.cpi.upsert(
            scenario.SERIES,
            CpiPoint(YearMonth(2026, 11), D(133)),
            base="2025=100",
            fetched_at=scenario.NOW,
        )
    assert monthly(6).status == "ok"
    assert notifier.sent[1][0].startswith("Aylık rapor (2026-11-30)")


def test_payday_message_is_sent(migrated_db: Path, clock: FixedClock) -> None:
    scenario.seed(migrated_db)
    notifier = FakeNotifier()
    context = _context(migrated_db, clock, notifier=notifier)

    result = job_body("payday", date(2026, 11, 15), context)()

    assert result.status == "ok"
    assert notifier.sent[0][0].startswith("Maaş günü (2026-11-15)")
    assert "<code>ft tx add</code>" in notifier.sent[0][0]


def test_cpi_sync_is_ok_only_when_the_target_period_arrives(
    migrated_db: Path, clock: FixedClock
) -> None:
    scenario.seed(migrated_db)
    november = FakeCpiSource(FetchResult([CpiPoint(YearMonth(2026, 11), D(133))], []))

    arrived = job_body("sync-cpi", date(2026, 11, 1), _context(migrated_db, clock, cpi=november))()
    waiting = job_body("sync-cpi", date(2026, 12, 1), _context(migrated_db, clock))()

    assert (arrived.status, waiting.status) == ("ok", "partial")


def test_messages_without_telegram_fail_clearly(migrated_db: Path, clock: FixedClock) -> None:
    scenario.seed(migrated_db)
    body = job_body("payday", date(2026, 11, 15), _context(migrated_db, clock))

    outcome = _run(migrated_db, "payday", date(2026, 11, 15), body, clock)

    assert outcome.status == "failed"
    assert "JobError: Telegram tanımlı değil" in str(outcome.detail["hata"])


def test_backup_job_records_the_file_and_trims_old_raw_payloads(
    migrated_db: Path, clock: FixedClock
) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        for key, age in (("eski", 31), ("yeni", 1)):
            fetched = clock.now() - timedelta(days=age)
            uow.raw_payloads.add(RawPayload("tefas", key, fetched, b"{}"))
    made: list[datetime] = []

    def backup(now: datetime) -> BackupOutcome:
        made.append(now)
        return BackupOutcome("finans-x.db.age", "abc", 10, "ok", ("finans-eski.db.age",))

    result = job_body("backup", SUNDAY, replace(_context(migrated_db, clock), backup=backup))()

    assert result.detail == {
        "dosya": "finans-x.db.age",
        "sha256": "abc",
        "boyut": 10,
        "bütünlük": "ok",
        "silinen_yedek": ["finans-eski.db.age"],
        "silinen_ham_yanıt": 1,
    }
    assert made == [clock.now()]


def test_backup_job_needs_its_settings(migrated_db: Path, clock: FixedClock) -> None:
    with pytest.raises(JobError, match="FT_BACKUP_DIR ve FT_BACKUP_AGE_RECIPIENTS"):
        job_body("backup", SUNDAY, _context(migrated_db, clock))()
