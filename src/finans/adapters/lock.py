import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class FlockJobLock:
    """İş başına bir kilit dosyası; süreç ölürse çekirdek kilidi bırakır."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @contextmanager
    def hold(self, job: str) -> Iterator[bool]:
        self._directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self._directory / f"{job}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
