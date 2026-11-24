"""TEFAS kayıt betiği: birkaç herkese açık fonun API yanıtını kaydeder.

Kullanıcı kendi makinesinde çalıştırır:  uv run python scripts/record_tefas.py

TEFAS'ın robots.txt dosyası /api/ yolunu otomatik erişime kapatıyor. Bu betik kullanıcının
bilinçli kararıyla ve şu sınırlarla çalışır: dürüst User-Agent, tarayıcı taklidi yok, en fazla
10 istek, istekler sıralı ve aralarında en az 10 sn. 403 ya da HTML/WAF sayfası gelirse durur;
engeli aşmaya çalışmaz. Yanıtlar bayt bayt var/tefas-kayit/<zaman>/ altına yazılır.
"""

import argparse
import json
import secrets
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from finans.settings import load_settings

BASE = "https://www.tefas.gov.tr"
PRICE_URL = f"{BASE}/api/funds/fonFiyatBilgiGetir"
LIST_URL = f"{BASE}/api/funds/fonGnlBlgSiraliGetir"
USER_AGENT = f"finans-takip/{version('finans-takip')} (kisisel kullanim)"
MIN_INTERVAL = 10
MAX_REQUESTS = 10
MAX_RETRY_AFTER = 300
DEFAULT_RETRY_AFTER = 60
TYPES = ("YAT", "EMK", "BYF")
ISTANBUL = ZoneInfo("Europe/Istanbul")
_SECOND = timedelta(seconds=1)


class Stop(Exception):
    """Kayıt durur; engel aşılmaya çalışılmaz."""


@dataclass
class Recorder:
    out: Path
    client: httpx.Client
    count: int = 0
    last: datetime | None = None
    lines: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        print(text)
        self.lines.append(text)

    def post(self, name: str, url: str, payload: dict[str, object]) -> object:
        for attempt in range(1, 4):
            self._wait_turn()
            if self.count >= MAX_REQUESTS:
                raise Stop(f"istek sınırına ({MAX_REQUESTS}) ulaşıldı")
            self.count += 1
            started = datetime.now(UTC)
            try:
                response = self.client.post(url, json=payload)
            except httpx.TransportError as exc:
                self.note(f"[{self.count:02d}] {name}: bağlantı hatası {type(exc).__name__}")
                time.sleep(2**attempt)
                continue
            elapsed = (datetime.now(UTC) - started) // timedelta(milliseconds=1)
            kind = self._save(name, url, payload, response, elapsed)
            status = response.status_code
            size = len(response.content)
            self.note(f"[{self.count:02d}] {name}: HTTP {status}, {size} bayt, {elapsed} ms")
            if status == 429:
                wait = _retry_after(response)
                if wait > MAX_RETRY_AFTER:
                    raise Stop(f"429; sunucu {wait} sn bekleme istedi")
                self.note(f"     429: {wait} sn bekleniyor")
                time.sleep(wait)
                continue
            if status >= 500:
                time.sleep(2**attempt)
                continue
            if status in (401, 403) or kind == "html":
                raise Stop(f"{name}: HTTP {status} ({kind}); engel aşılmaya çalışılmadı")
            if kind != "json":
                self.note(f"     yanıt JSON değil ({kind})")
                return None
            return json.loads(response.content, parse_float=Decimal)
        self.note(f"     {name}: 3 denemede alınamadı")
        return None

    def _wait_turn(self) -> None:
        if self.last is not None:
            gap = timedelta(seconds=MIN_INTERVAL + secrets.randbelow(3))
            remaining = gap - (datetime.now(UTC) - self.last)
            if remaining > timedelta(0):
                time.sleep(-(-remaining // _SECOND))
        self.last = datetime.now(UTC)

    def _save(
        self,
        name: str,
        url: str,
        payload: dict[str, object],
        response: httpx.Response,
        elapsed_ms: int,
    ) -> str:
        content_type = response.headers.get("Content-Type", "")
        body = response.content
        if "html" in content_type.lower() or body.lstrip()[:1] == b"<":
            kind = "html"
        elif not body.strip():
            kind = "bos"
        else:
            try:
                json.loads(body)
                kind = "json"
            except ValueError:
                kind = "metin"
        stem = f"{self.count:02d}_{name}"
        suffix = {"json": ".json", "html": ".html"}.get(kind, ".txt")
        (self.out / f"{stem}{suffix}").write_bytes(body)
        meta = {
            "method": "POST",
            "url": url,
            "request_json": payload,
            "user_agent": USER_AGENT,
            "status": response.status_code,
            "content_type": content_type,
            "retry_after": response.headers.get("Retry-After"),
            "elapsed_ms": elapsed_ms,
            "fetched_at": datetime.now(UTC).isoformat(),
            "kind": kind,
        }
        text = json.dumps(meta, ensure_ascii=False, indent=1)
        (self.out / f"{stem}.meta.json").write_text(text, encoding="utf-8")
        return kind


def _retry_after(response: httpx.Response) -> int:
    value = response.headers.get("Retry-After", "").strip()
    if value.isdigit():
        return int(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, -(-(when - datetime.now(UTC)) // _SECOND))


def _rows(data: object) -> list[dict[str, object]]:
    if isinstance(data, dict):
        for key in ("resultList", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _field(row: dict[str, object], name: str) -> object:
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
    return None


def _describe(rec: Recorder, data: object) -> None:
    if isinstance(data, dict):
        envelope = {k: v for k, v in data.items() if not isinstance(v, list)}
        rec.note(f"     zarf: {json.dumps(envelope, default=str, ensure_ascii=False)[:300]}")
    rows = _rows(data)
    rec.note(f"     satır: {len(rows)}")
    if not rows:
        return
    types = {key: type(value).__name__ for key, value in rows[0].items()}
    rec.note(f"     ilk satır alanları ve tipleri: {types}")
    prices = [str(p) for row in rows if (p := _field(row, "fiyat")) is not None]
    decimals = sorted({len(p.split(".")[1]) if "." in p else 0 for p in prices})
    zeros = sum(1 for p in prices if Decimal(p) == 0)
    dates = [str(_field(row, "tarih")) for row in rows]
    rec.note(f"     fiyat basamakları {decimals}; sıfır fiyatlı satır {zeros}")
    rec.note(f"     tarih: ilk {dates[0]!r}, son {dates[-1]!r}")


def _own_codes() -> set[str]:
    """Kullanıcının kendi fonları kayda girmesin diye portfolio.toml'daki kodlar."""
    candidates = [Path("config/portfolio.toml")]
    try:
        configured = load_settings().portfolio_path
    except ValidationError:
        configured = None
    if configured is not None:
        candidates.insert(0, configured)
    codes: set[str] = set()
    for path in candidates:
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            codes |= {str(item.get("code")) for item in data.get("instruments", [])}
    return codes


def _reference_day() -> date:
    day = datetime.now(ISTANBUL).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _list_payload(fund_type: str, code: str | None, start: date, end: date) -> dict[str, object]:
    # Çalışan istemcilerin gönderdiği biçim: boş alanlar null; basSira/bitSira olmadan sunucu
    # "Index 0 out of bounds for length 0" döndürüyor (ilk kayıt, 2026-11-24).
    return {
        "fonTipi": fund_type,
        "fonKodu": code,
        "aramaMetni": None,
        "fonTurKod": None,
        "fonGrubu": None,
        "sfonTurKod": None,
        "basTarih": start.strftime("%Y%m%d"),
        "bitTarih": end.strftime("%Y%m%d"),
        "basSira": 1,
        "bitSira": 9999,
        "fonTurAciklama": None,
        "dil": "TR",
        "kurucuKod": None,
        "sira": None,
        "yon": None,
    }


def _priced_codes(data: object, exclude: set[str]) -> list[str]:
    codes = []
    for row in _rows(data):
        code, price = _field(row, "fonKodu"), _field(row, "fiyat")
        if code and str(code) not in exclude and Decimal(str(price or 0)) > 0:
            codes.append(str(code))
    return sorted(codes)


def run(rec: Recorder, fixed: dict[str, str], exclude: set[str]) -> None:
    rec.note(f"User-Agent: {USER_AGENT}")
    robots = rec.client.get(f"{BASE}/robots.txt")
    rec.count += 1
    rec.last = datetime.now(UTC)
    (rec.out / "01_robots.txt").write_bytes(robots.content)
    api_lines = [line for line in robots.text.splitlines() if "/api/" in line]
    rec.note(f"[01] robots.txt: HTTP {robots.status_code}; /api/ satırları: {api_lines}")

    day = _reference_day()
    chosen: dict[str, str] = {}
    for fund_type in TYPES:
        if fund_type in fixed:
            chosen[fund_type] = fixed[fund_type]
            continue
        payload = _list_payload(fund_type, None, day, day)
        data = rec.post(f"liste_{fund_type}", LIST_URL, payload)
        _describe(rec, data)
        codes = _priced_codes(data, exclude)
        if codes:
            chosen[fund_type] = secrets.choice(codes)
    rec.note(f"seçilen fonlar: {chosen}")

    for fund_type, code in chosen.items():
        payload = {"fonKodu": code, "dil": "TR", "periyod": 1}
        _describe(rec, rec.post(f"fiyat_{fund_type}_{code}_1ay", PRICE_URL, payload))

    yat = chosen.get("YAT")
    if yat is None:
        return
    payload = {"fonKodu": yat, "dil": "TR", "periyod": 60}
    _describe(rec, rec.post(f"fiyat_YAT_{yat}_60ay", PRICE_URL, payload))
    for days in (28, 60):
        start = day - timedelta(days=days - 1)
        payload = _list_payload("YAT", yat, start, day)
        _describe(rec, rec.post(f"aralik_YAT_{yat}_{days}gun", LIST_URL, payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="TEFAS yanıtlarını kaydeder.")
    parser.add_argument("--out", type=Path, help="çıktı dizini; varsayılan var/tefas-kayit/<zaman>")
    parser.add_argument(
        "--fon", action="append", default=[], metavar="TİP=KOD", help="ör. --fon YAT=ABC"
    )
    parser.add_argument("--exclude", nargs="*", default=[], metavar="KOD", help="seçilmeyecek")
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path("var") / "tefas-kayit" / stamp
    out.mkdir(parents=True, exist_ok=False)
    fixed = dict(item.split("=", 1) for item in args.fon)
    exclude = set(args.exclude) | _own_codes()
    print(f"Dışarıda tutulan kod sayısı: {len(exclude)}")

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=False) as client:
        rec = Recorder(out, client)
        try:
            run(rec, fixed, exclude)
        except Stop as exc:
            rec.note(f"DURDU: {exc}")
        except KeyboardInterrupt:
            rec.note("DURDU: kullanıcı kesti")
        finally:
            (out / "ozet.txt").write_text("\n".join(rec.lines) + "\n", encoding="utf-8")
    print(f"\nKayıtlar: {out}  ({rec.count} istek)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
