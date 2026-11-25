"""Tek bir tarayıcı oturumu: çerezi saklar, formları aynı kökenden ve belirteçle gönderir."""

import re
from collections.abc import Mapping
from urllib.parse import urlencode

import httpx

from finans.web.session import csrf_token
from tests.support.web_client import WebClient

LOGIN = "kisi@example.com"
ORIGIN = "https://cihaz.ornek.ts.net"
ME = {"Tailscale-User-Login": LOGIN}
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
SESSION_KEY = "k" * 64
HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)" value="([^"]*)">')


class Browser:
    def __init__(self, client: WebClient) -> None:
        self.client = client
        self.cookie = ""

    def get(self, path: str) -> httpx.Response:
        response = self.client.get(path, headers={**ME, "Cookie": self.cookie})
        if not self.cookie:
            self.cookie = response.headers["set-cookie"].split(";", 1)[0]
        return response

    def token(self) -> str:
        """Kilitliyken sayfada form yok; istek yine de gönderilebilmeli."""
        if not self.cookie:
            self.get("/gercek/daha")
        session = self.cookie.split("=", 1)[1].split(".", 1)[0]
        return csrf_token(SESSION_KEY.encode(), session)

    def post(
        self,
        path: str,
        data: Mapping[str, str],
        *,
        headers: Mapping[str, str] = SAME_ORIGIN,
        token: str | None = None,
    ) -> httpx.Response:
        body = {"belirtec": token or self.token(), **data}
        return self.client.post(
            path,
            headers={
                **ME,
                **headers,
                "Cookie": self.cookie,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=urlencode(body).encode(),
        )

    def unlock(
        self,
        password: str,
        *,
        sonra: str = "/gercek/islemler",
        profile: str = "gercek",
        headers: Mapping[str, str] = SAME_ORIGIN,
        token: str | None = None,
    ) -> httpx.Response:
        data = {"sifre": password, "sonra": sonra}
        return self.post(f"/{profile}/kilit", data, headers=headers, token=token)


def hidden_fields(html: str, action: str) -> dict[str, str]:
    """`action`'a giden formun gizli alanları; belirteç hariç (Browser kendisi ekler)."""
    start = html.index(f'action="{action}"')
    form = html[start : html.index("</form>", start)]
    return {name: value for name, value in HIDDEN.findall(form) if name != "belirtec"}
