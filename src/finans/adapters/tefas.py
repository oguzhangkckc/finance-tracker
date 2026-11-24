import calendar
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, ValidationError

from finans.adapters._http import HttpClient
from finans.domain.models import DomainError, Instrument, InstrumentKind, PricePoint
from finans.ports.clock import Clock
from finans.ports.sources import FetchResult, RawPayload, SourceError

# fonFiyatBilgiGetir yalnızca bu dönemleri (ay) kabul eder; en çok 5 yıl geriye gider (K-71).
PERIODS = (1, 3, 6, 12, 36, 60)
# fonGnlBlgSiraliGetir bir aydan uzun aralığı reddeder; 28 gün (dahil) her ayda güvenli.
WINDOW = timedelta(days=28)
_FUND_TYPES = {
    InstrumentKind.TEFAS_YAT: "YAT",
    InstrumentKind.TEFAS_EMK: "EMK",
    InstrumentKind.TEFAS_BYF: "BYF",
}

_Rows = list[dict[str, object]]


class _Envelope(BaseModel):
    error_message: str | None = Field(default=None, alias="errorMessage")
    result_list: _Rows | None = Field(default=None, alias="resultList")


class TefasPriceSource:
    """TEFAS JSON API (K-71). İstekleri kullanıcı çalıştırır; tarayıcı taklidi yapılmaz."""

    name = "tefas"

    def __init__(self, http: HttpClient, *, base_url: str, clock: Clock) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/") + "/"
        self._clock = clock

    def fetch(self, inst: Instrument, start: date, end: date) -> FetchResult[PricePoint]:
        fund_type = _FUND_TYPES.get(inst.kind)
        if fund_type is None:
            raise SourceError(f"{inst.code} bir TEFAS fonu değil ({inst.kind})")
        periyod = _periyod(start, self._clock.today())
        # BYF'de fonFiyatBilgiGetir borsa fiyatını verir; birim pay değeri aralık uç noktasında
        # (K-72).
        if fund_type == "BYF" or periyod is None:
            rows, raw = self._by_range(inst.code, fund_type, start, end)
        else:
            rows, raw = self._by_period(inst.code, periyod)
        try:
            points = _points(inst.code, rows, start, end)
        except ValueError as exc:
            raise SourceError(f"TEFAS yanıtı beklenen biçimde değil ({inst.code}): {exc}") from exc
        return FetchResult(points, raw)

    def _by_period(self, code: str, periyod: int) -> tuple[_Rows, list[RawPayload]]:
        payload = {"fonKodu": code, "dil": "TR", "periyod": periyod}
        rows, raw = self._post("fonFiyatBilgiGetir", payload, f"{code}:periyod={periyod}")
        return rows, [raw]

    def _by_range(
        self, code: str, fund_type: str, start: date, end: date
    ) -> tuple[_Rows, list[RawPayload]]:
        rows: _Rows = []
        raws: list[RawPayload] = []
        for first, last in _windows(start, end):
            payload = _range_payload(fund_type, code, first, last)
            part, raw = self._post("fonGnlBlgSiraliGetir", payload, f"{code}:{first}:{last}")
            rows.extend(part)
            raws.append(raw)
        return rows, raws

    def _post(self, endpoint: str, payload: object, key: str) -> tuple[_Rows, RawPayload]:
        response = self._http.post_json(self._base_url + endpoint, payload)
        raw = RawPayload("tefas", f"{endpoint}:{key}", self._clock.now(), response.body)
        try:
            envelope = _Envelope.model_validate(response.data)
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
            raise SourceError(
                f"TEFAS yanıtı beklenen biçimde değil ({endpoint}, {key}): {fields}"
            ) from exc
        # Hatalar HTTP 200 içinde errorMessage ile gelir (ör. "Tarih aralığı 1 ayı aşamaz").
        if envelope.error_message:
            raise SourceError(f"TEFAS {endpoint} ({key}): {envelope.error_message}")
        return envelope.result_list or [], raw


def _periyod(start: date, today: date) -> int | None:
    for months in PERIODS:
        if start >= _months_before(today, months):
            return months
    return None


def _months_before(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    first = start
    while first <= end:
        last = min(end, first + WINDOW - timedelta(days=1))
        yield first, last
        first = last + timedelta(days=1)


def _range_payload(fund_type: str, code: str, first: date, last: date) -> dict[str, object]:
    # Açık kaynak istemcilerin gövdesi: bütün alanlar, boşlar null, sayfalama alanları dolu.
    return {
        "fonTipi": fund_type,
        "fonKodu": code,
        "aramaMetni": None,
        "fonTurKod": None,
        "fonGrubu": None,
        "sfonTurKod": None,
        "basTarih": first.strftime("%Y%m%d"),
        "bitTarih": last.strftime("%Y%m%d"),
        "basSira": 1,
        "bitSira": 9999,
        "fonTurAciklama": None,
        "dil": "TR",
        "kurucuKod": None,
        "sira": None,
        "yon": None,
    }


def _points(code: str, rows: _Rows, start: date, end: date) -> list[PricePoint]:
    prices: dict[date, Decimal] = {}
    for row in rows:
        row_code = row.get("fonKodu")
        if not isinstance(row_code, str):
            raise ValueError(f"fonKodu yok: {row!r}")
        if row_code != code:
            continue
        day = _day(row.get("tarih"))
        price = _price(day, row.get("fiyat"))
        if price is not None and start <= day <= end:
            prices[day] = price
    try:
        return [PricePoint(code, day, prices[day], "tefas") for day in sorted(prices)]
    except DomainError as exc:
        raise ValueError(str(exc)) from exc


def _day(value: object) -> date:
    text = value if isinstance(value, str) else ""
    if len(text) > 10 and text[10] == "T":
        text = text[:10]
    try:
        day = date.fromisoformat(text)
    except ValueError:
        day = None
    if day is None or day.isoformat() != text:
        raise ValueError(f"tarih {value!r} anlaşılamadı")
    return day


def _price(day: date, value: object) -> Decimal | None:
    if value is None:
        return None
    # Yalnızca metin, Decimal ve tam sayı kabul edilir; başka bir yoldan gelen ikili kayan noktalı
    # sayı burada reddedilir (K-62).
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError(f"{day}: fiyat {value!r} sayı değil")
    try:
        price = Decimal(value.strip() if isinstance(value, str) else value)
    except InvalidOperation as exc:
        raise ValueError(f"{day}: fiyat {value!r} sayı değil") from exc
    if not price.is_finite() or price < 0:
        raise ValueError(f"{day}: fiyat {value!r} geçersiz")
    # Fon açılmadan önceki ve yayımlanmayan günler 0 gelir; veri yok sayılır (K-71).
    return None if price == 0 else price
