from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from email.utils import format_datetime
from importlib.metadata import version

import httpx
import pytest
import respx

from finans.adapters._http import HttpClient
from finans.ports.sources import SourceError
from tests.fakes.clock import FixedClock

URL = "https://veri.example/series=TP.X&type=json"
SECRET = "gizli-anahtar-123"  # noqa: S105 - sahte test değeri
OK = httpx.Response(200, json={"items": []})


@pytest.fixture
def client(clock: FixedClock) -> Iterator[HttpClient]:
    with HttpClient(clock, secrets=[SECRET]) as http:
        yield http


@respx.mock
def test_json_numbers_stay_decimal_and_raw_body_is_kept(client: HttpClient) -> None:
    body = b'{"price": 1.123456789012345678, "count": 5}'
    respx.get(URL).respond(200, content=body, headers={"Content-Type": "application/json"})

    response = client.get_json(URL)

    assert response.data == {"price": Decimal("1.123456789012345678"), "count": 5}
    assert response.body == body


@respx.mock
def test_user_agent_is_honest_and_nothing_imitates_a_browser(client: HttpClient) -> None:
    route = respx.get(URL).mock(return_value=OK)

    client.get_json(URL, headers={"key": SECRET})

    sent = route.calls.last.request.headers
    assert sent["User-Agent"] == f"finans-takip/{version('finans-takip')} (kisisel kullanim)"
    assert sent["key"] == SECRET
    assert "Origin" not in sent
    assert "Referer" not in sent


@respx.mock
def test_server_errors_timeouts_and_html_bodies_are_retried_with_backoff(
    client: HttpClient, clock: FixedClock
) -> None:
    route = respx.get(URL)
    route.side_effect = [
        httpx.Response(503),
        httpx.ReadTimeout("yavaş"),
        OK,
    ]
    assert client.get_json(URL).data == {"items": []}
    assert clock.slept == [2, 4]

    route.side_effect = [
        httpx.Response(200, text="<html>bakım</html>", headers={"Content-Type": "text/html"}),
        httpx.Response(200, content=b"  "),
        OK,
    ]
    assert client.get_json(URL).data == {"items": []}


@respx.mock
def test_gives_up_after_three_attempts(client: HttpClient, clock: FixedClock) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(500))

    with pytest.raises(SourceError, match="3 denemede alınamadı: HTTP 500"):
        client.get_json(URL)

    assert route.call_count == 3
    assert clock.slept == [2, 4]


@respx.mock
def test_client_errors_are_not_retried_and_show_the_server_message(
    client: HttpClient, clock: FixedClock
) -> None:
    route = respx.get(URL).respond(
        403, json={"status": "403", "message": "Required request header 'key' is not present"}
    )

    with pytest.raises(SourceError, match="HTTP 403: Required request header 'key'"):
        client.get_json(URL)

    assert route.call_count == 1
    assert clock.slept == []


@respx.mock
def test_redirects_are_not_followed(client: HttpClient) -> None:
    respx.get(URL).respond(302, headers={"Location": "https://veri.example/"})
    with pytest.raises(SourceError, match="HTTP 302"):
        client.get_json(URL)


@respx.mock
def test_malformed_json_is_not_retried(client: HttpClient) -> None:
    route = respx.get(URL).respond(200, content=b'{"items": [', headers={"Content-Type": "json"})
    with pytest.raises(SourceError, match="geçerli JSON değil"):
        client.get_json(URL)
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("7", 7), (None, 60), ("soon", 60)],
)
@respx.mock
def test_429_honours_retry_after_seconds_or_waits_sixty(
    client: HttpClient, clock: FixedClock, retry_after: str | None, expected: int
) -> None:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    respx.get(URL).side_effect = [httpx.Response(429, headers=headers), OK]

    client.get_json(URL)

    assert clock.slept == [expected]


@respx.mock
def test_429_honours_retry_after_as_http_date(client: HttpClient, clock: FixedClock) -> None:
    when = format_datetime(clock.now() + timedelta(seconds=29, milliseconds=500), usegmt=True)
    respx.get(URL).side_effect = [httpx.Response(429, headers={"Retry-After": when}), OK]

    client.get_json(URL)

    assert clock.slept == [29]


@respx.mock
def test_429_asking_for_more_than_five_minutes_is_not_awaited(
    client: HttpClient, clock: FixedClock
) -> None:
    route = respx.get(URL).respond(429, headers={"Retry-After": "301"})

    with pytest.raises(SourceError, match="301 sn beklenmesini istedi; beklenmedi"):
        client.get_json(URL)

    assert route.call_count == 1
    assert clock.slept == []


@respx.mock
def test_secret_values_never_appear_in_error_messages(client: HttpClient) -> None:
    respx.get(URL).respond(401, json={"message": f"anahtar {SECRET} geçersiz"})

    with pytest.raises(SourceError) as failure:
        client.get_json(URL, headers={"key": SECRET})

    assert SECRET not in str(failure.value)
    assert "anahtar *** geçersiz" in str(failure.value)


@respx.mock
def test_requests_keep_the_minimum_interval(clock: FixedClock) -> None:
    respx.get(URL).mock(return_value=OK)
    with HttpClient(clock, min_interval=10) as client:
        client.get_json(URL)
        clock.advance(timedelta(seconds=4))
        client.get_json(URL)
        client.get_json(URL)
    assert clock.slept == [6, 10]
