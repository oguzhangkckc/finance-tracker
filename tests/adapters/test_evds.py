import json
from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
import respx

from finans.adapters._http import HttpClient
from finans.adapters.evds import EvdsCpiSource
from finans.domain.models import CpiPoint, YearMonth
from finans.ports.sources import RawPayload, SourceError
from tests.fakes.clock import FixedClock

# Yanıt biçimi şimdilik ikincil kaynaklara dayanıyor (alan adları, metin değerler, "2026-1").
# Anahtarla kaydedilen gerçek yanıt gelince bu sentetik örnek onunla değiştirilir (K-61).
BASE = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
SERIES = "TP.TUKFIY2025.GENEL"
COLUMN = "TP_TUKFIY2025_GENEL"
KEY = "deneme-anahtari"
URL = f"{BASE}series={SERIES}&startDate=01-01-2025&endDate=01-11-2026&type=json"
START, END = YearMonth(2025, 1), YearMonth(2026, 11)


def _body(*rows: tuple[str, object]) -> bytes:
    items = [{"Tarih": period, COLUMN: value, "UNIXTIME": 0} for period, value in rows]
    return json.dumps({"totalCount": len(items), "items": items}).encode()


@pytest.fixture
def source(clock: FixedClock) -> Iterator[EvdsCpiSource]:
    with HttpClient(clock, secrets=[KEY]) as http:
        yield EvdsCpiSource(http, api_key=KEY, base_url=BASE, clock=clock)


@respx.mock
def test_request_carries_the_key_only_in_the_header(
    source: EvdsCpiSource, clock: FixedClock
) -> None:
    body = _body(("2025-1", "88.578291"), ("2025-2", "90.1"))
    route = respx.get(URL).respond(200, content=body, headers={"Content-Type": "application/json"})

    result = source.fetch(SERIES, START, END)

    request = route.calls.last.request
    assert request.headers["key"] == KEY
    assert KEY not in str(request.url)
    assert result.points == [
        CpiPoint(YearMonth(2025, 1), Decimal("88.578291")),
        CpiPoint(YearMonth(2025, 2), Decimal("90.1")),
    ]
    assert result.raw == [RawPayload("evds", f"{SERIES}:2025-01:2026-11", clock.now(), body)]


@respx.mock
def test_values_keep_every_digit_whether_text_or_number(source: EvdsCpiSource) -> None:
    body = (
        b'{"items": [{"Tarih": "2026-1", "TP_TUKFIY2025_GENEL": 1.123456789012345678},'
        b' {"Tarih": "2026-02", "TP_TUKFIY2025_GENEL": "2.123456789012345678"},'
        b' {"Tarih": "2026-3", "TP_TUKFIY2025_GENEL": 104}]}'
    )
    respx.get(URL).respond(200, content=body, headers={"Content-Type": "application/json"})

    indexes = [point.index for point in source.fetch(SERIES, START, END).points]

    assert indexes == [Decimal("1.123456789012345678"), Decimal("2.123456789012345678"), 104]


@respx.mock
def test_missing_values_are_skipped(source: EvdsCpiSource) -> None:
    body = _body(
        ("2026-1", None), ("2026-2", ""), ("2026-3", "null"), ("2026-4", "ND"), ("2026-5", "105")
    )
    respx.get(URL).respond(200, content=body, headers={"Content-Type": "application/json"})

    assert source.fetch(SERIES, START, END).points == [CpiPoint(YearMonth(2026, 5), Decimal(105))]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"totalCount": 0}', "items"),
        (b'{"items": [{"Tarih": "2026-1"}]}', COLUMN),
        (_body(("2026-13", "100")), "2026-13"),
        (_body(("Ocak 2026", "100")), "Ocak 2026"),
        (_body(("2026-1", "yüz")), "yüz"),
        (_body(("2026-1", True)), "True"),
        (_body(("2026-1", "NaN")), "NaN"),
        (_body(("2026-1", "0")), "2026-01"),
    ],
)
@respx.mock
def test_unexpected_shapes_and_values_are_reported(
    source: EvdsCpiSource, body: bytes, message: str
) -> None:
    respx.get(URL).respond(200, content=body, headers={"Content-Type": "application/json"})
    with pytest.raises(SourceError, match="EVDS yanıtı beklenen biçimde değil") as failure:
        source.fetch(SERIES, START, END)
    assert message in str(failure.value)


@respx.mock
def test_rejected_key_is_reported_without_the_key(source: EvdsCpiSource) -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(403, json={"status": "403", "message": f"key {KEY} invalid"})
    )
    with pytest.raises(SourceError, match="HTTP 403") as failure:
        source.fetch(SERIES, START, END)
    assert KEY not in str(failure.value)
