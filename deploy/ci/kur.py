#!/usr/bin/python3 -I
"""Deploy çalıştırıcısı (K-133…K-135). `finans-deploy.service` (User=finans) bunu istek dosyası
görünce çalıştırır: dondurma, doğrulama, canlıya dokunmayan hazırlık ve elle kurulum kuralları.

Pi'nin sistem Python'uyla (3.12) ve yalnız standart kütüphaneyle çalışır; uygulamanın sanal
ortamından bağımsızdır, bozuk bir sürüm deploy'u ve geri dönüşü bozamaz. Pi'de uzantısız olarak
`/usr/local/lib/finans-deploy/kur` adıyla, root sahipli kurulur."""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum
from pathlib import Path
from typing import Final, Protocol
from zoneinfo import ZoneInfo

SHA: Final = re.compile(r"[0-9a-f]{40}")
IDENT: Final = re.compile(r"[0-9a-f]{32}")
ISTANBUL: Final = ZoneInfo("Europe/Istanbul")
UNITS: Final = Path("deploy/systemd")
MIGRATIONS: Final = Path("src/finans/adapters/sqlite/migrations")
SCRIPTS: Final = {"istek": Path("deploy/ci/istek.py"), "kur": Path("deploy/ci/kur.py")}
UNIT_PREFIX: Final = "finans-"
RESULT_MODE: Final = 0o640
COMMAND_TIMEOUT: Final = 15 * 60


class Kod(IntEnum):
    """Deploy işinin çıkış kodu (K-132); `istek`'tekiyle aynı olmalı (testle denetlenir)."""

    TAMAM = 0
    BASARISIZ = 1
    ELLE_KURULUM = 2
    RET = 3
    MESGUL = 4


@dataclass(frozen=True)
class Yollar:
    istek: Path
    sonuc: Path
    dondur: Path
    repo: Path
    surumler: Path
    current: Path
    python: Path
    uv_cache: Path
    systemd: Path
    betikler: Path


URETIM: Final = Yollar(
    istek=Path("/var/lib/finans-deploy/istek/deploy.request"),
    sonuc=Path("/var/lib/finans-deploy/sonuc"),
    dondur=Path("/etc/finans/deploy-dondur"),
    repo=Path("/opt/finans/repo.git"),
    surumler=Path("/opt/finans/releases"),
    current=Path("/opt/finans/current"),
    python=Path("/opt/finans/.python"),
    uv_cache=Path("/var/lib/finans-deploy/uv-cache"),
    systemd=Path("/etc/systemd/system"),
    betikler=Path("/usr/local/lib/finans-deploy"),
)


@dataclass(frozen=True)
class Sonuc:
    kod: Kod
    mesaj: str
    sha: str
    onceki: str | None = None


class Durdur(Exception):
    """Deploy bu adımda biter; sonuç yazılır ve bildirilir."""

    def __init__(self, sonuc: Sonuc) -> None:
        super().__init__(sonuc.mesaj)
        self.sonuc = sonuc


class Calistirici(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


def run(
    args: Sequence[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argümanlar listedir, kabuk yok
        list(args),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT,
    )


def short(sha: str) -> str:
    return sha[:7]


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "ayrıntı yok"


def read_request(paths: Yollar) -> tuple[str, str] | None:
    """İstek okunur ve silinir; çalışırken kilit tutulduğu için `istek` yine meşgul der."""
    try:
        text = paths.istek.read_text(encoding="ascii")
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    finally:
        paths.istek.unlink(missing_ok=True)
    lines = text.splitlines()
    if len(lines) != 2 or not SHA.fullmatch(lines[0]) or not IDENT.fullmatch(lines[1]):
        return None
    return lines[0], lines[1]


@dataclass(frozen=True)
class Dondurma:
    sebep: str
    bitis: date | None


def freeze(paths: Yollar, today: date) -> Dondurma | None:
    """Bitiş günü dahil dondurulmuştur. Okunamayan bitiş tarihi süresiz sayılır: belirsizlikte
    kurmamak güvenli olandır."""
    try:
        text = paths.dondur.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, equals, value = line.partition("=")
        if equals:
            fields[key.strip()] = value.strip()
    reason = fields.get("sebep") or "sebep yazılmamış"
    raw = fields.get("bitis", "")
    if not raw:
        return Dondurma(reason, None)
    try:
        until = date.fromisoformat(raw)
    except ValueError:
        return Dondurma(f"{reason} (bitiş tarihi okunamadı: {raw})", None)
    return None if today > until else Dondurma(reason, until)


def frozen_message(frozen: Dondurma, sha: str) -> str:
    until = "süresiz" if frozen.bitis is None else f"{frozen.bitis.isoformat()} dahil"
    return f"⏸ Deploy dondurulmuş: {frozen.sebep} ({until}). {short(sha)} kurulmadı."


def installed(paths: Yollar) -> str | None:
    try:
        target = os.readlink(paths.current)
    except OSError:
        return None
    name = Path(target).name
    return name if SHA.fullmatch(name) else None


def _git(paths: Yollar, runner: Calistirici, *args: str) -> subprocess.CompletedProcess[str]:
    return runner(["git", "-C", str(paths.repo), *args])


def verify(paths: Yollar, sha: str, runner: Calistirici = run) -> str:
    """Kurulu sürümü döndürür. Commit `main`'in atası olmalı, kurulu sürüm de onun atası olmalı
    (geriye dönüş yok); aynı commit zaten kuruluysa bir şey yapılmaz (K-134)."""
    current = installed(paths)
    if current is None:
        message = "⚠ Elle kurulum gerekiyor: `current` sürümü yok; D1 kurulumu tamamlanmamış."
        raise Durdur(Sonuc(Kod.ELLE_KURULUM, message, sha))
    if current == sha:
        message = f"{short(sha)} zaten kurulu; bir şey yapılmadı."
        raise Durdur(Sonuc(Kod.TAMAM, message, sha, current))
    # Bütün dallar çekilir: başka daldaki bir commit "bulunamadı" değil "`main`'de yok" diye
    # reddedilsin. Ata denetimi yalnız `origin/main`'e karşıdır.
    fetched = _git(
        paths, runner, "fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"
    )
    if fetched.returncode:
        message = f"❌ GitHub'dan çekilemedi: {last_line(fetched.stderr)}. Canlı sürüm değişmedi."
        raise Durdur(Sonuc(Kod.BASARISIZ, message, sha, current))
    if _git(paths, runner, "cat-file", "-e", f"{sha}^{{commit}}").returncode:
        message = f"Reddedildi: {short(sha)} GitHub'da bulunamadı."
        raise Durdur(Sonuc(Kod.RET, message, sha, current))
    on_main = _git(paths, runner, "merge-base", "--is-ancestor", sha, "refs/remotes/origin/main")
    if on_main.returncode:
        raise Durdur(Sonuc(Kod.RET, f"Reddedildi: {short(sha)} `main`'de yok.", sha, current))
    if _git(paths, runner, "merge-base", "--is-ancestor", current, sha).returncode:
        message = (
            f"Reddedildi: kurulu sürüm ({short(current)}) {short(sha)} commit'inin atası değil; "
            "geriye dönüş yapılmaz."
        )
        raise Durdur(Sonuc(Kod.RET, message, sha, current))
    return current


def discard(paths: Yollar, release: Path, runner: Calistirici = run) -> None:
    _git(paths, runner, "worktree", "remove", "--force", str(release))
    if release.exists():
        shutil.rmtree(release)
    _git(paths, runner, "worktree", "prune")


def prepare(paths: Yollar, sha: str, current: str, runner: Calistirici = run) -> Path:
    """Yeni sürüm kendi dizininde ve kendi sanal ortamıyla hazırlanır; canlıya dokunulmaz."""
    release = paths.surumler / sha
    if release.exists():
        discard(paths, release, runner)
    added = _git(paths, runner, "worktree", "add", "--detach", str(release), sha)
    if added.returncode:
        message = (
            f"❌ Sürüm dizini hazırlanamadı: {last_line(added.stderr)}. Canlı sürüm değişmedi."
        )
        raise Durdur(Sonuc(Kod.BASARISIZ, message, sha, current))
    env = {
        **os.environ,
        "UV_PYTHON_INSTALL_DIR": str(paths.python),
        "UV_CACHE_DIR": str(paths.uv_cache),
    }
    synced = runner(["uv", "sync", "--locked", "--no-dev"], cwd=release, env=env)
    if synced.returncode:
        discard(paths, release, runner)
        message = (
            f"❌ Hazırlık başarısız (uv sync): {last_line(synced.stderr)}. Canlı sürüm değişmedi."
        )
        raise Durdur(Sonuc(Kod.BASARISIZ, message, sha, current))
    return release


def _files(root: Path) -> Iterator[Path]:
    if root.is_dir():
        yield from (path.relative_to(root) for path in root.rglob("*") if path.is_file())


def _installed_units(systemd: Path) -> Iterator[Path]:
    """Yalnız bu projenin birimleri; `*.wants` bağları ve diğer servisler sayılmaz."""
    if not systemd.is_dir():
        return
    for entry in sorted(systemd.iterdir()):
        if not entry.name.startswith(UNIT_PREFIX):
            continue
        if entry.is_dir():
            yield from (Path(entry.name) / name for name in _files(entry))
        elif entry.is_file():
            yield Path(entry.name)


def _same(left: Path, right: Path) -> bool:
    try:
        return left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def manual_reasons(paths: Yollar, release: Path, current_release: Path) -> list[str]:
    """Birim dosyaları, deploy betikleri ya da migration'lar elle kurulum ister (K-134)."""
    reasons: list[str] = []
    wanted = set(_files(release / UNITS))
    present = set(_installed_units(paths.systemd))
    units = sorted(
        str(name)
        for name in wanted | present
        if not _same(release / UNITS / name, paths.systemd / name)
    )
    if units:
        reasons.append(f"birim dosyası değişti ({', '.join(units)})")
    scripts = [
        name
        for name, source in SCRIPTS.items()
        if not _same(release / source, paths.betikler / name)
    ]
    if scripts:
        reasons.append(f"deploy betiği değişti ({', '.join(scripts)})")
    new = {path.name for path in (release / MIGRATIONS).glob("*.sql")}
    old = {path.name for path in (current_release / MIGRATIONS).glob("*.sql")}
    added = sorted(new - old)
    if added:
        reasons.append(f"yeni migration ({', '.join(added)})")
    changed = sorted(
        name
        for name in new & old
        if not _same(release / MIGRATIONS / name, current_release / MIGRATIONS / name)
    )
    if changed:
        reasons.append(f"uygulanmış migration değişti ({', '.join(changed)})")
    return reasons


def manual_message(reasons: Sequence[str], sha: str) -> str:
    return (
        f"⚠ Elle kurulum gerekiyor: {'; '.join(reasons)}. {short(sha)} kurulmadı; "
        "hazırlanan dizin silindi."
    )


def write_result(paths: Yollar, ident: str, result: Sonuc, now: datetime) -> Path:
    """Geçici dosya yazılıp yerine konur; `istek` yarım bir sonuç okumaz."""
    target = paths.sonuc / f"{ident}.json"
    temporary = paths.sonuc / f".{ident}.json.tmp"
    data = {
        "sha": result.sha,
        "kod": int(result.kod),
        "mesaj": result.mesaj,
        "onceki": result.onceki,
        "zaman": now.isoformat(timespec="seconds"),
    }
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.chmod(RESULT_MODE)
    os.replace(temporary, target)
    return target


def today_in_istanbul(clock: Callable[[], datetime] = lambda: datetime.now(ISTANBUL)) -> date:
    return clock().astimezone(ISTANBUL).date()
