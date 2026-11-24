import subprocess
from collections.abc import Sequence
from pathlib import Path

from finans.ports.backup import BackupError


class AgeEncryptor:
    """age programını (işletim sistemi paketi) yalnızca açık anahtarlarla çağırır (K-82)."""

    def __init__(self, binary: str = "age") -> None:
        self._binary = binary

    def encrypt(self, source: Path, target: Path, recipients: Sequence[str]) -> None:
        if not recipients:
            raise BackupError("age alıcısı tanımlı değil")
        command = [self._binary]
        for recipient in recipients:
            command += ["-r", recipient]
        command += ["-o", str(target), str(source)]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise BackupError(f"{self._binary} bulunamadı; age paketini kur") from exc
        except subprocess.CalledProcessError as exc:
            reason = (exc.stderr or "").strip()[:200] or f"çıkış kodu {exc.returncode}"
            raise BackupError(f"age şifreleyemedi: {reason}") from exc
