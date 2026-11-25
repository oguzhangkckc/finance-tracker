"""Yazma şifre kilidi (K-105, K-126). Açık oturumlar ve yanlış şifre sayacı bellektedir;
servis yeniden başlayınca sıfırlanır. Sayaç bütün oturumlar için ortaktır."""

import logging
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from finans.application.password import verify_password
from finans.ports.clock import Clock

UNLOCK_FOR: Final = timedelta(minutes=15)
LOCKOUT_FOR: Final = timedelta(minutes=15)
MAX_FAILURES: Final = 5
_LOG = logging.getLogger("finans.web")


@dataclass(frozen=True, slots=True)
class LockState:
    status: Literal["disabled", "locked", "open"]
    minutes_left: int = 0


@dataclass(frozen=True, slots=True)
class Attempt:
    status: Literal["ok", "wrong", "locked", "disabled"]
    attempts_left: int = 0
    until: datetime | None = None


class WriteLock:
    def __init__(self, stored: str | None, clock: Clock) -> None:
        self._stored = stored
        self._clock = clock
        self._open: dict[str, datetime] = {}
        self._failures = 0
        self._locked_until: datetime | None = None
        self._state = threading.Lock()
        # Denemeler sırayla: eşzamanlı istekler sayacı aşamasın, her scrypt 32 MiB ister.
        self._attempt = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._stored is not None

    def state(self, session: str) -> LockState:
        if self._stored is None:
            return LockState("disabled")
        now = self._clock.now()
        with self._state:
            until = self._open.get(session)
        if until is None or until <= now:
            return LockState("locked")
        return LockState("open", math.ceil((until - now).total_seconds() / 60))

    def is_open(self, session: str) -> bool:
        return self.state(session).status == "open"

    def lockout_until(self) -> datetime | None:
        now = self._clock.now()
        with self._state:
            until = self._locked_until
        return until if until is not None and now < until else None

    def try_unlock(self, session: str, password: str) -> Attempt:
        if self._stored is None:
            return Attempt("disabled")
        with self._attempt:
            now = self._clock.now()
            if (until := self.lockout_until()) is not None:
                return Attempt("locked", until=until)
            matched = verify_password(password, self._stored)
            with self._state:
                if matched:
                    self._failures = 0
                    self._open = {key: end for key, end in self._open.items() if end > now}
                    self._open[session] = now + UNLOCK_FOR
                    return Attempt("ok")
                self._failures += 1
                if self._failures < MAX_FAILURES:
                    return Attempt("wrong", attempts_left=MAX_FAILURES - self._failures)
                self._failures = 0
                self._locked_until = now + LOCKOUT_FOR
            _LOG.warning(
                "Yazma kilidi %d yanlış şifreden sonra %d dakika kapatıldı.",
                MAX_FAILURES,
                LOCKOUT_FOR // timedelta(minutes=1),
            )
            return Attempt("locked", until=self._locked_until)
