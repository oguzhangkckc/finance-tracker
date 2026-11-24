from collections.abc import Mapping

from finans.adapters._http import HttpClient


class HealthcheckPing:
    """healthchecks.io uyumlu ping; başarısızlıkta URL'nin sonuna /fail eklenir (K-84)."""

    def __init__(self, http: HttpClient, urls: Mapping[str, str]) -> None:
        self._http = http
        self._urls = dict(urls)

    def ping(self, check: str, *, ok: bool) -> None:
        url = self._urls.get(check)
        if url is None:
            return
        self._http.touch(url if ok else f"{url.rstrip('/')}/fail")
