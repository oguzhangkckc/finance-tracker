import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from finans.adapters.unix_listener import listen_unix


@pytest.fixture
def short_dir() -> Iterator[Path]:
    # Unix soket yolu macOS'ta ~104 baytla sınırlı; pytest'in geçici dizinleri daha uzun.
    with tempfile.TemporaryDirectory(prefix="ftw", dir="/tmp") as path:
        yield Path(path)


def test_socket_is_created_owner_only_and_listening(short_dir: Path) -> None:
    path = short_dir / "web.sock"

    listener = listen_unix(path)
    try:
        mode = path.lstat().st_mode
        assert stat.S_ISSOCK(mode)
        assert stat.S_IMODE(mode) == 0o600
        assert listener.family == socket.AF_UNIX
    finally:
        listener.close()


def test_a_stale_socket_is_replaced(short_dir: Path) -> None:
    path = short_dir / "web.sock"
    listen_unix(path).close()

    listener = listen_unix(path)
    listener.close()

    assert stat.S_ISSOCK(path.lstat().st_mode)


def test_a_regular_file_is_never_removed(short_dir: Path) -> None:
    path = short_dir / "web.sock"
    path.write_text("dokunma", encoding="utf-8")

    with pytest.raises(FileExistsError, match="soket değil"):
        listen_unix(path)

    assert path.read_text(encoding="utf-8") == "dokunma"
