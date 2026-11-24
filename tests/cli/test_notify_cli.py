import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans import bootstrap
from finans.adapters.render.json import JsonRenderer
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.cli.main import app
from finans.contracts.report import AlertNotice
from finans.ports.clock import Clock
from finans.ports.notifier import Notifier
from finans.ports.repositories import AlertState
from finans.settings import Settings
from tests.fakes.notifier import FakeNotifier

runner = CliRunner()
TOKEN = "123456:ABC-def_789"  # noqa: S105 - sahte test değeri
OPENED = datetime(2026, 11, 21, 18, 35, tzinfo=UTC)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "finans.db"
    monkeypatch.setenv("FT_DB_PATH", str(path))
    assert runner.invoke(app, ["db", "migrate"]).exit_code == 0
    return path


def _use(monkeypatch: pytest.MonkeyPatch, fake: FakeNotifier) -> None:
    @contextmanager
    def channel(_settings: Settings, _clock: Clock) -> Iterator[Notifier]:
        yield fake

    monkeypatch.setattr(bootstrap, "notifier", channel)


@pytest.mark.usefixtures("db")
def test_notify_test_without_telegram_settings_explains_what_to_do() -> None:
    result = runner.invoke(app, ["notify", "test"])
    assert result.exit_code == 1
    assert "FT_TELEGRAM_BOT_TOKEN ve FT_TELEGRAM_CHAT_ID tanımlı olmalı" in result.output


@pytest.mark.usefixtures("db")
def test_notify_test_sends_one_message(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeNotifier()
    _use(monkeypatch, fake)

    result = runner.invoke(app, ["notify", "test"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Test mesajı gönderildi."
    assert fake.sent == [("finans-takip: Telegram bağlantısı çalışıyor.", False)]


@pytest.mark.usefixtures("db")
def test_notify_test_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, FakeNotifier(fail=True))

    result = runner.invoke(app, ["notify", "test"])

    assert result.exit_code == 1
    assert "Hata: Telegram mesajı gönderilemedi" in result.output


@pytest.mark.usefixtures("db")
def test_doctor_shows_whether_telegram_is_set_never_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FT_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("FT_TELEGRAM_CHAT_ID", "42")

    result = runner.invoke(app, ["doctor"])

    assert "✓ Telegram: token ve sohbet ID'si tanımlı" in result.output
    assert TOKEN not in result.output


def test_alerts_lists_open_alarms_and_the_quiet_period(db: Path) -> None:
    empty = runner.invoke(app, ["alerts"])
    assert "Sessiz dönem: sürüyor (K-75)" in empty.output
    assert "Açık alarm yok." in empty.output

    with SqliteUnitOfWork(db) as uow:
        uow.allocation_state.end_quiet(date(2026, 11, 20))
        uow.alerts.save(AlertState("drift:hisse", "below", OPENED, None, None, "{}"))
    result = runner.invoke(app, ["alerts"])

    assert "Sessiz dönem: 2026-11-20 tarihinde bitti" in result.output
    assert "hisse: hedefin altında, açılış 2026-11-21 18:35 UTC, son bildirim yok" in result.output


def test_json_alerts_are_a_list_of_notices() -> None:
    notice = AlertNotice(
        kind="opened",
        asset_class="hisse",
        direction="below",
        deviation=Decimal("-0.14"),
        opened_at=OPENED,
    )
    assert json.loads(JsonRenderer().alerts([notice])) == [
        {
            "kind": "opened",
            "asset_class": "hisse",
            "direction": "below",
            "deviation": "-0.14",
            "opened_at": "2026-11-21T18:35:00Z",
        }
    ]
