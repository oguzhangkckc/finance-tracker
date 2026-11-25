"""Zamanlanmış işlerin tek giriş noktası (K-80): kayıt, kilit, idempotency ve ping."""

import json
import logging
import re
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal

from finans.application.alerts import deliver_alerts, evaluate_alerts, is_quiet_hour
from finans.application.backup import BackupOutcome
from finans.application.cpi import sync_cpi
from finans.application.price_sync import TEFAS_KINDS, sync_prices
from finans.application.report import ReportKind, build_report, payday_plan
from finans.contracts.report import Profile
from finans.domain.models import YearMonth
from finans.domain.portfolio import PortfolioConfig
from finans.ports.clock import Clock
from finans.ports.notifier import Notifier, NotifyError
from finans.ports.operations import HealthPing, JobLock
from finans.ports.render import ReportRenderer
from finans.ports.sources import CpiSource, PriceSource
from finans.ports.unit_of_work import UnitOfWork

Outcome = Literal["ok", "partial", "failed", "skipped", "busy"]
PING_CHECKS: Final = {"weekly-report": "reports", "monthly-report": "reports", "backup": "backup"}
CPI_WAIT_LAST_DAY: Final = 10
RAW_PAYLOAD_RETENTION: Final = timedelta(days=30)
PAYDAY_WINDOW: Final = timedelta(days=3)
_BOT_TOKEN: Final = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
_LOG = logging.getLogger("finans.jobs")


class JobError(Exception):
    """İş yapılandırması eksik ya da iş bu sürümde yok."""


@dataclass(frozen=True, slots=True)
class JobResult:
    status: Literal["ok", "partial"]
    detail: dict[str, object]


@dataclass(frozen=True, slots=True)
class JobOutcome:
    job: str
    logical_date: date
    status: Outcome
    detail: dict[str, object]


@dataclass(frozen=True, slots=True)
class JobContext:
    config: PortfolioConfig
    open_uow: Callable[[], UnitOfWork]
    clock: Clock
    cpi_series: str
    cpi_base: str
    price_source: Callable[[], AbstractContextManager[PriceSource]]
    cpi_source: Callable[[], AbstractContextManager[CpiSource]]
    notifier: Callable[[], AbstractContextManager[Notifier]] | None
    renderer: ReportRenderer
    weekly_enabled: bool
    backup: Callable[[datetime], BackupOutcome] | None = None
    profile: Profile = "real"


def run_job(
    job: str,
    logical_date: date,
    body: Callable[[], JobResult],
    *,
    open_uow: Callable[[], UnitOfWork],
    lock: JobLock,
    clock: Clock,
    ping: HealthPing | None = None,
    secrets: Sequence[str] = (),
) -> JobOutcome:
    """Her deneme job_run'da ayrı satırdır; aynı gün "ok" varsa iş çalışmaz (K-12)."""
    with lock.hold(job) as acquired:
        if not acquired:
            return JobOutcome(job, logical_date, "busy", {})
        with open_uow() as uow:
            if uow.runs.has_ok(job, logical_date):
                return JobOutcome(job, logical_date, "skipped", {})
            for stale in uow.runs.running(job):
                note = json.dumps(
                    {"hata": "önceki deneme yarıda kaldı; devralındı"}, ensure_ascii=False
                )
                uow.runs.finish(stale.id, "failed", note, at=clock.now())
            run_id = uow.runs.start(job, logical_date, at=clock.now())
        fields = {"job": job, "run_id": run_id, "logical_date": logical_date}
        _LOG.info("iş başladı", extra=fields)
        status: Literal["ok", "partial", "failed"]
        try:
            result = body()
            status, detail = result.status, dict(result.detail)
        except Exception as exc:  # İşin her hatası kaydedilir; iz sırlardan arındırılmış mesajdır.
            status, detail = "failed", {"hata": _redact(f"{type(exc).__name__}: {exc}", secrets)}
        check = PING_CHECKS.get(job)
        if ping is not None and check is not None and status != "partial":
            try:
                ping.ping(check, ok=status == "ok")
            except Exception as exc:  # Ping sorunu işin sonucunu değiştirmez.
                detail["ping"] = _redact(f"gönderilemedi: {exc}", secrets)
        text = json.dumps(detail, ensure_ascii=False, default=str)
        with open_uow() as uow:
            uow.runs.finish(run_id, status, text, at=clock.now())
        _LOG.info(_redact(f"iş bitti: {text}", secrets), extra={**fields, "status": status})
        return JobOutcome(job, logical_date, status, detail)


def job_body(job: str, logical_date: date, ctx: JobContext) -> Callable[[], JobResult]:
    bodies: dict[str, Callable[[date, JobContext], JobResult]] = {
        "sync-prices": _sync_prices,
        "sync-cpi": _sync_cpi,
        "weekly-report": _weekly_report,
        "monthly-report": _monthly_report,
        "payday": _payday,
        "backup": _backup,
    }
    if job not in bodies:
        raise JobError(f"tanınmayan iş: {job}")
    return lambda: bodies[job](logical_date, ctx)


def _redact(message: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return _BOT_TOKEN.sub("bot***", message)


def _sync_prices(day: date, ctx: JobContext) -> JobResult:
    with ctx.price_source() as source:
        report = sync_prices(source, ctx.open_uow, end=day, now=ctx.clock.now())
    detail: dict[str, object] = {
        "fon": len(report.funds),
        "hata": [f"{fund.code}: {fund.error}" for fund in report.funds if fund.error],
    }
    if report.stopped is not None:
        detail["durduruldu"] = report.stopped
    with ctx.open_uow() as uow:
        funds = [
            s.instrument.code for s in uow.instruments.list() if s.instrument.kind in TEFAS_KINDS
        ]
        missing = [code for code in funds if uow.prices.on(code, day) is None]
    if missing or not report.ok:
        # K-85: fiyatlar eksikken alarm değerlendirilmez; bekleyen bildirimler yine gider.
        detail.update(eksik=missing, alarm="atlandı: fiyat eksik")
        _deliver(ctx, detail)
        return JobResult("partial", detail)
    with ctx.open_uow() as uow:
        evaluation = evaluate_alerts(uow, ctx.config, on=day, now=ctx.clock.now())
    detail["alarm"] = (
        f"değerlendirildi, {len(evaluation.events)} olay"
        if evaluation.evaluated
        else f"atlandı: {evaluation.reason}"
    )
    return JobResult("ok" if _deliver(ctx, detail) else "partial", detail)


def _deliver(ctx: JobContext, detail: dict[str, object]) -> bool:
    if ctx.notifier is None:
        detail["bildirim"] = "Telegram tanımlı değil"
        return True
    try:
        with ctx.notifier() as notifier:
            sent = deliver_alerts(
                ctx.open_uow,
                notifier,
                ctx.renderer,
                now=ctx.clock.now(),
                reminder_days=ctx.config.alerts.reminder_days,
            )
    except NotifyError as exc:
        detail["bildirim"] = f"gönderilemedi, sonra denenecek: {exc}"
        return False
    detail["bildirim"] = sent
    return True


def _sync_cpi(day: date, ctx: JobContext) -> JobResult:
    target = YearMonth.of(day)
    with ctx.cpi_source() as source:
        report = sync_cpi(
            source,
            ctx.open_uow,
            series=ctx.cpi_series,
            base=ctx.cpi_base,
            start=target.shift(-3),
            end=target,
            now=ctx.clock.now(),
        )
    detail: dict[str, object] = {
        "alınan": report.received,
        "revize": len(report.revised),
        "son_dönem": str(report.latest),
    }
    ready = report.latest is not None and report.latest >= target
    return JobResult("ok" if ready else "partial", detail)


def _weekly_report(day: date, ctx: JobContext) -> JobResult:
    if not ctx.weekly_enabled:
        return JobResult("ok", {"gönderim": "haftalık rapor kapalı (FT_WEEKLY_REPORT_ENABLED)"})
    return _send_report(ctx, "weekly", day, note=None)


def _monthly_report(day: date, ctx: JobContext) -> JobResult:
    """Önceki ayın TÜFE'si gelince bir kez; 10'unda hâlâ yoksa bayat-TÜFE notuyla (K-13)."""
    target = YearMonth.of(day)
    with ctx.open_uow() as uow:
        latest = uow.cpi.latest(ctx.cpi_series)
    note = None
    if latest is None or latest.period < target:
        if ctx.clock.today().day < CPI_WAIT_LAST_DAY:
            return JobResult("partial", {"gönderim": f"{target} TÜFE'si bekleniyor"})
        note = f"Not: {target} TÜFE'si henüz yok; en son dönemle hesaplandı."
    return _send_report(ctx, "monthly", day, note=note)


def _send_report(ctx: JobContext, kind: ReportKind, day: date, *, note: str | None) -> JobResult:
    with ctx.open_uow() as uow:
        report = build_report(
            uow,
            ctx.config,
            kind=kind,
            logical_date=day,
            now=ctx.clock.now(),
            cpi_series=ctx.cpi_series,
            profile=ctx.profile,
        )
    text = ctx.renderer.report(report)
    _send(ctx, text if note is None else f"{note}\n\n{text}")
    return JobResult("ok", {"gönderim": "gönderildi", "eksik_fiyat": report.missing_prices})


def _payday(day: date, ctx: JobContext) -> JobResult:
    """Zamanlayıcı her gün çalışır; mesaj yalnızca maaş gününden sonraki 3 gün içinde gider,
    böylece ilk kurulumda geçmiş ayın mesajı gönderilmez (K-97)."""
    if ctx.clock.today() - day > PAYDAY_WINDOW:
        return JobResult("ok", {"gönderim": "atlandı: pencere geçti", "maaş_günü": str(day)})
    with ctx.open_uow() as uow:
        plan = payday_plan(uow, ctx.config, on=day, profile=ctx.profile)
    _send(ctx, ctx.renderer.payday(plan))
    return JobResult("ok", {"gönderim": "gönderildi", "eksik_fiyat": plan.missing_prices})


def _send(ctx: JobContext, text: str) -> None:
    if ctx.notifier is None:
        raise JobError(
            "Telegram tanımlı değil; FT_TELEGRAM_BOT_TOKEN ve FT_TELEGRAM_CHAT_ID gerekli"
        )
    with ctx.notifier() as notifier:
        notifier.send(text, silent=is_quiet_hour(ctx.clock.now()))


def _backup(day: date, ctx: JobContext) -> JobResult:
    """Şifreli gece yedeği ve 30 günden eski ham yanıtların silinmesi (K-82)."""
    if ctx.backup is None:
        raise JobError("FT_BACKUP_DIR ve FT_BACKUP_AGE_RECIPIENTS tanımlı olmalı (K-82)")
    now = ctx.clock.now()
    outcome = ctx.backup(now)
    with ctx.open_uow() as uow:
        deleted = uow.raw_payloads.delete_before(now - RAW_PAYLOAD_RETENTION)
    return JobResult(
        "ok",
        {
            "dosya": outcome.name,
            "sha256": outcome.sha256,
            "boyut": outcome.size,
            "bütünlük": outcome.integrity,
            "silinen_yedek": list(outcome.removed),
            "silinen_ham_yanıt": deleted,
        },
    )
