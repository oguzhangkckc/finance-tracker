#!/usr/bin/python3 -I
"""Deploy kullanıcısının zorunlu komutu (K-133). Yalnız `deploy <40 küçük hex>` kabul eder, istek
dosyası bırakır ve çalıştırıcının (`kur`) sonucunu bekler. Ağa çıkmaz, hiçbir şey kurmaz.

Pi'nin sistem Python'uyla (3.12) ve yalnız standart kütüphaneyle çalışır; Pi'de uzantısız olarak
`/usr/local/lib/finans-deploy/istek` adıyla, root sahipli kurulur."""

import fcntl
import json
import os
import re
import secrets
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Final

COMMAND: Final = re.compile(r"deploy ([0-9a-f]{40})")
WAIT_SECONDS: Final = 20 * 60
POLL_SECONDS: Final = 2
REQUEST_MODE: Final = 0o640


class Kod(IntEnum):
    """Deploy işinin çıkış kodu (K-132)."""

    TAMAM = 0
    BASARISIZ = 1
    ELLE_KURULUM = 2
    RET = 3
    MESGUL = 4


@dataclass(frozen=True)
class Yollar:
    """`istek`: bekleyen istek; `sonuc`: çalıştırıcının sonuç dizini; `kilit`: çalıştırıcının
    çalışırken tuttuğu kilit."""

    istek: Path
    sonuc: Path
    kilit: Path


URETIM: Final = Yollar(
    istek=Path("/var/lib/finans-deploy/istek/deploy.request"),
    sonuc=Path("/var/lib/finans-deploy/sonuc"),
    kilit=Path("/var/lib/finans-deploy/sonuc/kur.lock"),
)
REFUSED: Final = "Reddedildi: yalnız `deploy <40 haneli küçük harfli commit sha>` kabul edilir."
BUSY: Final = "Meşgul: başka bir deploy bekliyor ya da sürüyor; bitince yeniden çalıştır."
UNREADABLE: Final = "Sonuç dosyası okunamadı; Pi'de `journalctl -u finans-deploy.service` ile bak."


def say(text: str) -> None:
    """Çıktı SSH üzerinden CI işinin günlüğüne gider."""
    sys.stdout.write(f"{text}\n")


def requested_sha(command: str | None) -> str | None:
    """Boşluk, satır sonu, büyük harf ya da ek argüman kabul edilmez."""
    if command is None:
        return None
    match = COMMAND.fullmatch(command)
    return match.group(1) if match else None


def busy(paths: Yollar) -> bool:
    if paths.istek.exists():
        return True
    try:
        fd = os.open(paths.kilit, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def leave_request(paths: Yollar, sha: str, ident: str) -> None:
    """Geçici dosya yazılır ve `link` ile yerine konur: yarım dosya görünmez, iki istek aynı anda
    gelirse ikincisi FileExistsError alır."""
    temporary = paths.istek.with_name(f".{paths.istek.name}.{ident}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, REQUEST_MODE)
    try:
        os.fchmod(fd, REQUEST_MODE)
        os.write(fd, f"{sha}\n{ident}\n".encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(temporary, paths.istek)
    finally:
        temporary.unlink()


def wait_result(
    paths: Yollar,
    ident: str,
    *,
    timeout: float = WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> tuple[Kod, str]:
    """Yalnız bu isteğin kimliğiyle yazılmış sonuç okunur; önceki bir çalışmanınki değil."""
    result = paths.sonuc / f"{ident}.json"
    deadline = now() + timeout
    while True:
        if result.exists():
            return _parse(result)
        if now() >= deadline:
            minutes = round(timeout / 60)
            return Kod.BASARISIZ, (
                f"Sonuç {minutes} dakikada gelmedi; durum bilinmiyor. Pi'de "
                "`journalctl -u finans-deploy.service` ile bak."
            )
        sleep(poll)


def _parse(result: Path) -> tuple[Kod, str]:
    try:
        data = json.loads(result.read_text(encoding="utf-8"))
        return Kod(int(data["kod"])), str(data["mesaj"])
    except (OSError, ValueError, KeyError, TypeError):
        return Kod.BASARISIZ, UNREADABLE


def main(
    environ: Mapping[str, str] = os.environ,
    paths: Yollar = URETIM,
    wait: Callable[[Yollar, str], tuple[Kod, str]] = wait_result,
) -> int:
    sha = requested_sha(environ.get("SSH_ORIGINAL_COMMAND"))
    if sha is None:
        say(REFUSED)
        return Kod.RET
    if busy(paths):
        say(BUSY)
        return Kod.MESGUL
    ident = secrets.token_hex(16)
    try:
        leave_request(paths, sha, ident)
    except FileExistsError:
        say(BUSY)
        return Kod.MESGUL
    code, message = wait(paths, ident)
    say(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
