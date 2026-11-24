import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from finans.adapters._http import HttpClient
from finans.adapters.telegram import LIMIT, TelegramNotifier, split_message
from finans.ports.notifier import NotifyError
from tests.fakes.clock import FixedClock

TOKEN = "123456:ABC-def_789"  # noqa: S105 - sahte test değeri
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
SENT = httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


@pytest.fixture
def notifier(clock: FixedClock) -> Iterator[TelegramNotifier]:
    with HttpClient(clock, secrets=[TOKEN]) as http:
        yield TelegramNotifier(http, token=TOKEN, chat_id="42", base_url="https://api.telegram.org")


@respx.mock
def test_message_goes_to_the_configured_chat_as_html(notifier: TelegramNotifier) -> None:
    route = respx.post(URL).mock(return_value=SENT)

    notifier.send("Rapor\n<code>ft tx add</code>", silent=True)

    body = json.loads(route.calls.last.request.content)
    assert body == {
        "chat_id": "42",
        "text": "Rapor\n<code>ft tx add</code>",
        "parse_mode": "HTML",
        "disable_notification": True,
        "link_preview_options": {"is_disabled": True},
    }


@respx.mock
def test_long_message_is_sent_in_parts_split_at_sections(notifier: TelegramNotifier) -> None:
    route = respx.post(URL).mock(return_value=SENT)
    first, second = "a" * 3000, "b" * 3000

    notifier.send(f"{first}\n\n{second}", silent=False)

    assert [json.loads(call.request.content)["text"] for call in route.calls] == [first, second]


def test_oversized_section_is_split_at_lines_and_oversized_line_by_length() -> None:
    lines = "\n".join(["x" * 3000, "y" * 3000])
    assert split_message(lines) == ["x" * 3000, "y" * 3000]
    assert split_message("z" * (LIMIT + 10)) == ["z" * LIMIT, "z" * 10]
    assert split_message("kısa\n\nmesaj") == ["kısa\n\nmesaj"]


@respx.mock
def test_rejected_message_is_an_error_with_telegrams_reason(notifier: TelegramNotifier) -> None:
    respx.post(URL).respond(200, json={"ok": False, "description": "can't parse entities"})

    with pytest.raises(NotifyError, match="can't parse entities"):
        notifier.send("<b>", silent=False)


@respx.mock
def test_http_failure_is_an_error_without_the_token(notifier: TelegramNotifier) -> None:
    respx.post(URL).respond(400, json={"ok": False, "description": "Bad Request: chat not found"})

    with pytest.raises(NotifyError) as failure:
        notifier.send("deneme", silent=False)

    assert TOKEN not in str(failure.value)
    assert "chat not found" in str(failure.value)


@respx.mock
def test_prefix_opens_every_message(clock: FixedClock) -> None:
    route = respx.post(URL).mock(return_value=SENT)
    with HttpClient(clock, secrets=[TOKEN]) as http:
        prefixed = TelegramNotifier(
            http, token=TOKEN, chat_id="42", base_url="https://api.telegram.org", prefix="ÖNEK"
        )
        prefixed.send("Rapor", silent=True)

    assert json.loads(route.calls.last.request.content)["text"] == "ÖNEK\n\nRapor"
