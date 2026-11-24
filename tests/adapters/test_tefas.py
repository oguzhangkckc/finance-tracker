import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from finans.adapters._http import HttpClient
from finans.adapters.tefas import TefasPriceSource
from finans.domain.models import Instrument, InstrumentKind, PricePoint
from finans.ports.sources import RawPayload, SourceError
from tests.fakes.clock import FixedClock

# Kayıtlı gerçek yanıtlar (2026-11-24, K-71); kaynakları tests/fixtures/tefas/README.md'de.
FIXTURES = Path(__file__).parents[1] / "fixtures" / "tefas"
BASE = "https://www.tefas.gov.tr/api/funds/"
PRICE_URL = f"{BASE}fonFiyatBilgiGetir"
RANGE_URL = f"{BASE}fonGnlBlgSiraliGetir"
EMPTY = b'{"errorCode":null,"errorMessage":null,"resultList":[]}'
BCO = Instrument("BCO", InstrumentKind.TEFAS_YAT, "karma")
AJH = Instrument("AJH", InstrumentKind.TEFAS_EMK, "emeklilik")
EOZ = Instrument("EOZ", InstrumentKind.TEFAS_BYF, "hisse")
D = Decimal


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _ok(body: bytes) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})


def _bodies(route: respx.Route) -> list[dict[str, object]]:
    return [json.loads(call.request.content) for call in route.calls]


@pytest.fixture
def source(clock: FixedClock) -> Iterator[TefasPriceSource]:
    with HttpClient(clock) as http:
        yield TefasPriceSource(http, base_url=BASE, clock=clock)


@respx.mock
def test_recent_prices_come_from_the_price_endpoint_and_are_filtered(
    source: TefasPriceSource, clock: FixedClock
) -> None:
    body = _fixture("fiyat_bco_periyod1.json")
    route = respx.post(PRICE_URL).mock(return_value=_ok(body))

    result = source.fetch(BCO, date(2026, 11, 2), date(2026, 11, 20))

    assert _bodies(route) == [{"fonKodu": "BCO", "dil": "TR", "periyod": 1}]
    days = [point.price_date for point in result.points]
    assert days == sorted(days)
    assert (days[0], days[-1]) == (date(2026, 11, 2), date(2026, 11, 20))
    assert result.points[-1] == PricePoint("BCO", date(2026, 11, 20), D("1.744322"), "tefas")
    assert result.raw == [
        RawPayload("tefas", "fonFiyatBilgiGetir:BCO:periyod=1", clock.now(), body)
    ]


@pytest.mark.parametrize(
    ("start", "periyod"),
    [
        (date(2026, 11, 1), 1),
        (date(2026, 10, 23), 1),
        (date(2026, 10, 22), 3),
        (date(2026, 6, 1), 6),
        (date(2025, 12, 1), 12),
        (date(2024, 1, 1), 36),
        (date(2021, 11, 23), 60),
    ],
)
@respx.mock
def test_smallest_period_covering_the_start_is_requested(
    source: TefasPriceSource, start: date, periyod: int
) -> None:
    route = respx.post(PRICE_URL).mock(return_value=_ok(EMPTY))
    assert source.fetch(BCO, start, date(2026, 11, 23)).points == []
    assert _bodies(route)[0]["periyod"] == periyod


@respx.mock
def test_days_before_the_fund_opened_are_skipped(source: TefasPriceSource) -> None:
    respx.post(PRICE_URL).mock(return_value=_ok(_fixture("fiyat_bco_periyod60.json")))

    points = source.fetch(BCO, date(2021, 12, 1), date(2026, 11, 24)).points

    assert len(points) == 393 - 16
    assert points[0] == PricePoint("BCO", date(2025, 5, 27), D("0.99994"), "tefas")
    assert all(point.price > 0 for point in points)


@respx.mock
def test_pension_fund_prices_are_read_the_same_way(source: TefasPriceSource) -> None:
    respx.post(PRICE_URL).mock(return_value=_ok(_fixture("fiyat_ajh_periyod1.json")))

    points = source.fetch(AJH, date(2026, 10, 26), date(2026, 11, 24)).points

    assert len(points) == 21
    assert {point.instrument for point in points} == {"AJH"}


@respx.mock
def test_etf_uses_the_unit_value_from_the_range_endpoint(source: TefasPriceSource) -> None:
    route = respx.post(RANGE_URL).mock(return_value=_ok(_fixture("liste_byf_2026-11-23.json")))

    points = source.fetch(EOZ, date(2026, 11, 23), date(2026, 11, 23)).points

    # Borsa bülten fiyatı 22.03; birim pay değeri 21.968691 (K-72). Diğer BYF'ler yok sayılır.
    assert points == [PricePoint("EOZ", date(2026, 11, 23), D("21.968691"), "tefas")]
    assert _bodies(route) == [
        {
            "fonTipi": "BYF",
            "fonKodu": "EOZ",
            "aramaMetni": None,
            "fonTurKod": None,
            "fonGrubu": None,
            "sfonTurKod": None,
            "basTarih": "20261123",
            "bitTarih": "20261123",
            "basSira": 1,
            "bitSira": 9999,
            "fonTurAciklama": None,
            "dil": "TR",
            "kurucuKod": None,
            "sira": None,
            "yon": None,
        }
    ]


@respx.mock
def test_range_rows_arrive_newest_first_and_are_returned_in_date_order(
    source: TefasPriceSource,
) -> None:
    respx.post(RANGE_URL).mock(return_value=_ok(_fixture("aralik_bco_28gun.json")))
    etf_shaped = Instrument("BCO", InstrumentKind.TEFAS_BYF, "karma")

    points = source.fetch(etf_shaped, date(2026, 10, 27), date(2026, 11, 23)).points

    assert len(points) == 19
    assert points[0].price_date == date(2026, 10, 27)
    assert points[-1] == PricePoint("BCO", date(2026, 11, 23), D("1.715559"), "tefas")


@respx.mock
def test_history_older_than_five_years_is_fetched_in_28_day_windows(
    source: TefasPriceSource,
) -> None:
    route = respx.post(RANGE_URL).mock(return_value=_ok(EMPTY))

    source.fetch(BCO, date(2021, 10, 1), date(2021, 12, 31))

    windows = [(body["basTarih"], body["bitTarih"]) for body in _bodies(route)]
    assert windows == [
        ("20211001", "20211028"),
        ("20211029", "20211125"),
        ("20211126", "20211223"),
        ("20211224", "20211231"),
    ]
    assert {body["fonTipi"] for body in _bodies(route)} == {"YAT"}


@respx.mock
def test_error_message_inside_a_200_is_a_source_error(source: TefasPriceSource) -> None:
    respx.post(RANGE_URL).mock(return_value=_ok(_fixture("aralik_bco_60gun_hata.json")))
    with pytest.raises(SourceError, match="Tarih aralığı 1 ayı aşamaz"):
        source.fetch(EOZ, date(2026, 11, 23), date(2026, 11, 23))


@respx.mock
def test_prices_keep_every_digit(source: TefasPriceSource) -> None:
    body = _fixture("fiyat_bco_periyod1.json").replace(
        b'"fiyat":1.77324}', b'"fiyat":1.123456789012345678}', 1
    )
    respx.post(PRICE_URL).mock(return_value=_ok(body))

    first = source.fetch(BCO, date(2026, 10, 26), date(2026, 10, 26)).points

    assert first == [PricePoint("BCO", date(2026, 10, 26), D("1.123456789012345678"), "tefas")]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"resultList": {"fiyat": 1}}', "resultList"),
        (b'{"resultList": [{"fonKodu": "BCO", "tarih": "24.11.2026", "fiyat": 1}]}', "24.11.2026"),
        (b'{"resultList": [{"fonKodu": "BCO", "tarih": "2026-11-20", "fiyat": true}]}', "True"),
        (b'{"resultList": [{"fonKodu": "BCO", "tarih": "2026-11-20", "fiyat": "bir"}]}', "bir"),
        (b'{"resultList": [{"fonKodu": "BCO", "tarih": "2026-11-20", "fiyat": -1}]}', "-1"),
        (b'{"resultList": [{"tarih": "2026-11-20", "fiyat": 1}]}', "fonKodu"),
    ],
)
@respx.mock
def test_unexpected_shapes_are_reported(
    source: TefasPriceSource, body: bytes, message: str
) -> None:
    respx.post(PRICE_URL).mock(return_value=_ok(body))
    with pytest.raises(SourceError, match="TEFAS yanıtı beklenen biçimde değil") as failure:
        source.fetch(BCO, date(2026, 11, 2), date(2026, 11, 20))
    assert message in str(failure.value)


@respx.mock
def test_null_result_list_means_no_prices(source: TefasPriceSource) -> None:
    respx.post(PRICE_URL).mock(return_value=_ok(b'{"errorMessage": null, "resultList": null}'))
    assert source.fetch(BCO, date(2026, 11, 2), date(2026, 11, 20)).points == []


def test_manual_instruments_are_not_tefas_funds(source: TefasPriceSource) -> None:
    gold = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")
    with pytest.raises(SourceError, match="TEFAS fonu değil"):
        source.fetch(gold, date(2026, 11, 2), date(2026, 11, 20))
