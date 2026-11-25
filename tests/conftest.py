import decimal
import os
import socket
import time
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest
from hypothesis import settings

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled
from tests.fakes.clock import FixedClock

# Testler performans ölçmüyor; süre sınırı makine yüküne göre rastgele kırılıyordu.
settings.register_profile("finans", deadline=None)
settings.load_profile("finans")


def _network_blocked(*_args: object, **_kwargs: object) -> NoReturn:
    raise RuntimeError(
        "Testlerde ağ erişimi kapalı; gerçek ağa çıkan testi @pytest.mark.live ile işaretle."
    )


_CONNECT = socket.socket.connect
_CONNECT_EX = socket.socket.connect_ex


def _local_connect(self: socket.socket, address: object) -> None:
    """Unix soketi ağ değil, yerel süreçler arası iletişim (ör. deploy'un web soketi denetimi)."""
    if self.family != socket.AF_UNIX:
        _network_blocked()
    _CONNECT(self, address)  # type: ignore[arg-type]


def _local_connect_ex(self: socket.socket, address: object) -> int:
    if self.family != socket.AF_UNIX:
        _network_blocked()
    return _CONNECT_EX(self, address)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live") is not None:
        return
    monkeypatch.setattr(socket.socket, "connect", _local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _local_connect_ex)
    monkeypatch.setattr(socket, "create_connection", _network_blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _network_blocked)


@pytest.fixture(autouse=True)
def _strict_decimal() -> Iterator[None]:
    context = decimal.getcontext()
    previous = context.traps[decimal.FloatOperation]
    context.traps[decimal.FloatOperation] = True
    yield
    context.traps[decimal.FloatOperation] = previous


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("FT_") or key == "CREDENTIALS_DIRECTORY":
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(params=["Europe/Istanbul", "UTC", "Pacific/Kiritimati", "America/Los_Angeles"])
def system_zone(request: pytest.FixtureRequest) -> Iterator[str]:
    """Sistem saat dilimi değiştirilmez (K-99); uygulama yerel saate hiç bakmamalı."""
    zone: str = request.param
    previous = os.environ.get("TZ")
    os.environ["TZ"] = zone
    time.tzset()
    yield zone
    if previous is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))


@pytest.fixture
def migrated_db(tmp_path: Path, clock: FixedClock) -> Path:
    path = tmp_path / "finans.db"
    with closing(connect(path)) as conn:
        apply(conn, bundled(), clock=clock)
    return path
