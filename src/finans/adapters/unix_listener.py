import os
import socket
import stat
from pathlib import Path

BACKLOG = 64


def listen_unix(path: Path, *, mode: int = 0o600) -> socket.socket:
    """Unix soketini izniyle birlikte açar; uvicorn kendi bağladığı sokete 0666 verir (K-123)."""
    if path.exists() or path.is_symlink():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise FileExistsError(f"{path} bir soket değil; silinmedi.")
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        previous = os.umask(0o777 & ~mode)
        try:
            listener.bind(str(path))
        finally:
            os.umask(previous)
        path.chmod(mode)
        listener.listen(BACKLOG)
    except BaseException:
        listener.close()
        raise
    return listener
