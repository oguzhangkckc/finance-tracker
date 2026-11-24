import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ValidationError

from finans.adapters._http import HttpClient
from finans.domain.models import CpiPoint, DomainError, YearMonth
from finans.ports.clock import Clock
from finans.ports.sources import FetchResult, RawPayload, SourceError

_PERIOD = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})$")
_MISSING_TEXT = frozenset({"", "null", "ND"})


class _Envelope(BaseModel):
    items: list[dict[str, object]]


class EvdsCpiSource:
    """EVDS3 web servisi (K-61); anahtar yalnızca `key` başlığında gider."""

    def __init__(self, http: HttpClient, *, api_key: str, base_url: str, clock: Clock) -> None:
        self._http = http
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/"
        self._clock = clock

    def fetch(self, series: str, start: YearMonth, end: YearMonth) -> FetchResult[CpiPoint]:
        url = (
            f"{self._base_url}series={series}&startDate={_first_day(start)}"
            f"&endDate={_first_day(end)}&type=json"
        )
        response = self._http.get_json(url, headers={"key": self._api_key})
        raw = RawPayload("evds", f"{series}:{start}:{end}", self._clock.now(), response.body)
        try:
            points = _parse(series, response.data)
        except ValueError as exc:
            raise SourceError(f"EVDS yanıtı beklenen biçimde değil: {exc}") from exc
        return FetchResult(points, [raw])


def _first_day(period: YearMonth) -> str:
    # EVDS tarihleri gg-aa-yyyy ister; dönemin ilk günü yazılmazsa o dönem sonuca girmez.
    return f"01-{period.month:02d}-{period.year:04d}"


def _parse(series: str, data: object) -> list[CpiPoint]:
    try:
        envelope = _Envelope.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        raise ValueError(f"alan eksik ya da hatalı: {fields}") from exc
    column = series.replace(".", "_")
    points: list[CpiPoint] = []
    for item in envelope.items:
        if column not in item:
            raise ValueError(f"{column} sütunu yok")
        period = _period(item.get("Tarih"))
        index = _index(period, item[column])
        if index is None:
            continue
        try:
            points.append(CpiPoint(period, index))
        except DomainError as exc:
            raise ValueError(str(exc)) from exc
    return points


def _period(value: object) -> YearMonth:
    match = _PERIOD.match(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"dönem {value!r} anlaşılamadı")
    try:
        return YearMonth(int(match["year"]), int(match["month"]))
    except DomainError as exc:
        raise ValueError(f"dönem {value!r}: {exc}") from exc


def _index(period: YearMonth, value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and value.strip() in _MISSING_TEXT):
        return None
    # Yalnızca metin, Decimal ve tam sayı kabul edilir; başka bir yoldan gelen ikili kayan noktalı
    # sayı burada reddedilir (K-62).
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError(f"{period}: değer {value!r} sayı değil")
    try:
        index = Decimal(value.strip() if isinstance(value, str) else value)
    except InvalidOperation as exc:
        raise ValueError(f"{period}: değer {value!r} sayı değil") from exc
    if not index.is_finite():
        raise ValueError(f"{period}: değer {value!r} sayı değil")
    return index
