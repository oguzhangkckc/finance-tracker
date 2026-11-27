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

# Bağlı bir worktree'de `git rebase --exec` ve git kancaları GIT_DIR'ı mutlak yolla dışa aktarır;
# testlerin geçici depolarda çalıştırdığı git komutları o zaman gerçek depoya yazar (2026-11-26:
# ana depo bare oldu). Liste `git rev-parse --local-env-vars`; test, eksiksiz olduğunu denetler.
GIT_LOCAL_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)
for _name in GIT_LOCAL_ENV:
    os.environ.pop(_name, None)


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
