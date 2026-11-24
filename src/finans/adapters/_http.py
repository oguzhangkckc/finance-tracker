import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from importlib.metadata import version
from types import TracebackType
from typing import Self

import httpx

from finans.ports.clock import Clock
from finans.ports.sources import SourceError

USER_AGENT = f"finans-takip/{version('finans-takip')} (kisisel kullanim)"
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 20
DEFAULT_RETRY_AFTER = 60
MAX_RETRY_AFTER = 300
_SECOND = timedelta(seconds=1)


@dataclass(frozen=True, slots=True)
class JsonResponse:
    data: object
    body: bytes


class _Retryable(Exception):
    def __init__(self, reason: str, wait: int) -> None:
        super().__init__(reason)
        self.wait = wait


class HttpClient:
    """K-62: dürüst User-Agent, sıralı istek, retry ve Retry-After; JSON'da float yok."""

    def __init__(
        self,
        clock: Clock,
        *,
        min_interval: int = 0,
        jitter: Callable[[], int] | None = None,
        secrets: Sequence[str] = (),
    ) -> None:
        self._clock = clock
        self._min_interval = timedelta(seconds=min_interval)
        self._jitter = jitter
        self._secrets = tuple(s for s in secrets if s)
        self._last_request: datetime | None = None
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_json(self, url: str, *, headers: Mapping[str, str] | None = None) -> JsonResponse:
        return self._send("GET", url, headers or {}, None)

    def post_json(
        self, url: str, payload: object, *, headers: Mapping[str, str] | None = None
    ) -> JsonResponse:
        return self._send("POST", url, headers or {}, payload)

    def _send(
        self, method: str, url: str, headers: Mapping[str, str], payload: object
    ) -> JsonResponse:
        reason = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._attempt(method, url, headers, payload, backoff=2**attempt)
            except _Retryable as retry:
                reason = str(retry)
                if attempt < MAX_ATTEMPTS:
                    self._clock.sleep(retry.wait)
        raise SourceError(self._redact(f"{url}: {MAX_ATTEMPTS} denemede alınamadı: {reason}"))

    def _attempt(
        self, method: str, url: str, headers: Mapping[str, str], payload: object, *, backoff: int
    ) -> JsonResponse:
        self._wait_turn()
        try:
            if payload is None:
                response = self._client.request(method, url, headers=headers)
            else:
                response = self._client.request(method, url, headers=headers, json=payload)
        except httpx.TransportError as exc:
            raise _Retryable(f"bağlantı hatası ({type(exc).__name__})", backoff) from exc
        status = response.status_code
        if status == 429:
            wait = self._retry_after(response)
            if wait > MAX_RETRY_AFTER:
                raise SourceError(
                    self._redact(
                        f"{url}: HTTP 429; sunucu {wait} sn beklenmesini istedi; beklenmedi"
                    )
                )
            raise _Retryable("HTTP 429", wait)
        if status >= 500:
            raise _Retryable(f"HTTP {status}", backoff)
        if not response.is_success:
            raise SourceError(self._redact(f"{url}: HTTP {status}: {_server_message(response)}"))
        body = response.content
        if not body.strip() or "html" in response.headers.get("Content-Type", "").lower():
            raise _Retryable("boş ya da HTML gövde", backoff)
        try:
            data = json.loads(body, parse_float=Decimal)
        except ValueError as exc:
            raise SourceError(self._redact(f"{url}: yanıt geçerli JSON değil")) from exc
        return JsonResponse(data, body)

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            gap = self._min_interval
            if self._jitter is not None:
                gap += timedelta(seconds=self._jitter())
            remaining = gap - (self._clock.now() - self._last_request)
            if remaining > timedelta(0):
                self._clock.sleep(_ceil_seconds(remaining))
        self._last_request = self._clock.now()

    def _retry_after(self, response: httpx.Response) -> int:
        value = response.headers.get("Retry-After", "").strip()
        if value.isdigit():
            return int(value)
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return DEFAULT_RETRY_AFTER
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0, _ceil_seconds(when - self._clock.now()))

    def _redact(self, message: str) -> str:
        for secret in self._secrets:
            message = message.replace(secret, "***")
        return message


def _ceil_seconds(delta: timedelta) -> int:
    return -(-delta // _SECOND)


def _server_message(response: httpx.Response) -> str:
    try:
        payload = json.loads(response.content, parse_float=Decimal)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return str(payload["message"])
    return response.text[:200].strip() or response.reason_phrase
