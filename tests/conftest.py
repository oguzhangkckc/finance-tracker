import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest

from tests.fakes.clock import FixedClock


def _network_blocked(*_args: object, **_kwargs: object) -> NoReturn:
    raise RuntimeError(
        "Testlerde ağ erişimi kapalı; gerçek ağa çıkan testi @pytest.mark.live ile işaretle."
    )


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live") is not None:
        return
    monkeypatch.setattr(socket.socket, "connect", _network_blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _network_blocked)
    monkeypatch.setattr(socket, "create_connection", _network_blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _network_blocked)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("FT_") or key == "CREDENTIALS_DIRECTORY":
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
