"""Elle fiyat güncellemesi: kural domain'de, istek dosyası adapter'da; fiyatı iş çeker (K-123)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from finans.domain.refresh import RefreshDecision, refresh_decision
from finans.ports.clock import BUSINESS_TZ
from finans.ports.operations import RefreshRequests
from finans.ports.unit_of_work import UnitOfWork

SYNC_JOB: Final = "sync-prices"
_LOOKBACK: Final = timedelta(days=2)


@dataclass(frozen=True, slots=True)
class RefreshStatus:
    decision: RefreshDecision
    last_sync: datetime | None


def refresh_status(uow: UnitOfWork, requests: RefreshRequests, *, now: datetime) -> RefreshStatus:
    finished = [
        run.finished_at
        for run in uow.runs.recent(since=now - _LOOKBACK)
        if run.job == SYNC_JOB and run.finished_at is not None
    ]
    last_sync = max(finished, default=None)
    decision = refresh_decision(
        now.astimezone(BUSINESS_TZ), accepted=requests.accepted(), last_sync=last_sync
    )
    return RefreshStatus(decision, last_sync)


def request_refresh(uow: UnitOfWork, requests: RefreshRequests, *, now: datetime) -> RefreshStatus:
    status = refresh_status(uow, requests, now=now)
    if status.decision.allowed:
        requests.request(now)
    return status
