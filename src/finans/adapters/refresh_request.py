import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

_KEEP: Final = timedelta(days=2)


class FileRefreshRequests:
    """`<profil>.request` istek dosyası; `<profil>.log` kabul edilen isteklerin anları (K-123)."""

    def __init__(self, directory: Path, profile: str) -> None:
        self._directory = directory
        self._request = directory / f"{profile}.request"
        self._log = directory / f"{profile}.log"

    def accepted(self) -> list[datetime]:
        if not self._log.exists():
            return []
        moments = []
        for line in self._log.read_text(encoding="utf-8").splitlines():
            try:
                moment = datetime.fromisoformat(line.strip())
            except ValueError:
                continue
            if moment.tzinfo is not None:
                moments.append(moment)
        return moments

    def request(self, now: datetime) -> None:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        recent = [moment for moment in self.accepted() if now - moment < _KEEP]
        lines = "".join(f"{moment.isoformat()}\n" for moment in [*recent, now])
        self._replace(self._log, lines)
        # .path birimi dosyanın varlığını izler; atomik yazım yarım dosya göstermez.
        self._replace(self._request, f"{now.isoformat()}\n")

    def _replace(self, target: Path, text: str) -> None:
        handle, partial = tempfile.mkstemp(dir=self._directory, prefix=f".{target.name}.")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(text)
            Path(partial).replace(target)
        except BaseException:
            Path(partial).unlink(missing_ok=True)
            raise
