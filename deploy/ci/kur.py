#!/usr/bin/python3 -I
"""Deploy çalıştırıcısı (K-133…K-135). `finans-deploy.service` (User=finans) bunu istek dosyası
görünce çalıştırır: dondurma, doğrulama, canlıya dokunmayan hazırlık, elle kurulum kuralları,
zamanlayıcı penceresi ve iş kilitleri, atomik geçiş, sağlık denetimi ve gerekirse geri dönüş.

Pi'nin sistem Python'uyla (3.12) ve yalnız standart kütüphaneyle çalışır; uygulamanın sanal
ortamından bağımsızdır, bozuk bir sürüm deploy'u ve geri dönüşü bozamaz. Pi'de uzantısız olarak
`/usr/local/lib/finans-deploy/kur` adıyla, root sahipli kurulur."""

import fcntl
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
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
TIMER_WINDOW: Final = 15 * 60
LOCK_WAIT: Final = 10 * 60
WEB_WAIT: Final = 60
HEALTH_WAIT: Final = 3 * 60
PAGE_WAIT: Final = 30
POLL: Final = 2
KEEP_RELEASES: Final = 3
WEB_UNIT: Final = "finans-web.service"
HEALTH_UNIT: Final = "finans-deploy-saglik.service"
PAGES: Final = ("/gercek/", "/sanal/")
TIMER_NAME: Final = re.compile(r"finans-(sanal-)?([a-z][a-z-]*)\.timer")


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
    kilitler: tuple[Path, Path]
    web_istek: Path
    saglik: Path
    soket: Path


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
    kilitler=(Path("/var/lib/finans/locks"), Path("/var/lib/finans/locks/sanal")),
    web_istek=Path("/var/lib/finans-deploy/web-yeniden-baslat"),
    saglik=Path("/var/lib/finans-deploy/saglik"),
    soket=Path("/run/finans-web/web.sock"),
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


type Uyku = Callable[[float], None]
type Saat = Callable[[], float]


def upcoming_timer(
    runner: Calistirici, now: float, window: int = TIMER_WINDOW
) -> tuple[str, float] | None:
    """Önümüzdeki `window` saniyede çalışacak ilk `finans-*` zamanlayıcısı. Zamanlayıcılar
    okunamazsa deploy yapılmaz: belirsizlikte işle çakışmamak güvenli olandır."""
    shown = runner(
        [
            "systemctl",
            "show",
            "--timestamp=unix",
            "-p",
            "Id",
            "-p",
            "NextElapseUSecRealtime",
            "finans-*.timer",
        ]
    )
    if shown.returncode:
        return "zamanlayıcılar okunamadı", now
    due: list[tuple[float, str]] = []
    for block in shown.stdout.strip().split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        value = fields.get("NextElapseUSecRealtime", "")
        if value.startswith("@") and value[1:].isdigit():
            moment = float(value[1:])
            if now <= moment <= now + window:
                due.append((moment, fields.get("Id", "bilinmeyen zamanlayıcı")))
    if not due:
        return None
    moment, name = min(due)
    return name, moment


def lock_files(paths: Yollar) -> list[Path]:
    """Her zamanlanmış işin kilidi ve var olan bütün kilitler; olmayan dosya oluşturulur, yoksa iş
    geçiş sırasında kendi kilidini alabilirdi."""
    real, sanal = paths.kilitler
    files = {path for directory in paths.kilitler for path in directory.glob("*.lock")}
    if paths.systemd.is_dir():
        for entry in paths.systemd.iterdir():
            match = TIMER_NAME.fullmatch(entry.name)
            if match:
                files.add((sanal if match.group(1) else real) / f"{match.group(2)}.lock")
    return sorted(files)


def _try_locks(files: Sequence[Path]) -> tuple[list[int], list[str]]:
    held: list[int] = []
    busy: list[str] = []
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            busy.append(path.stem if path.parent.name != "sanal" else f"sanal/{path.stem}")
        else:
            held.append(descriptor)
    return held, busy


def _release(held: Sequence[int]) -> None:
    for descriptor in held:
        os.close(descriptor)


@contextmanager
def job_locks(files: Sequence[Path], *, wait: float, sleep: Uyku, now: Saat) -> Iterator[list[str]]:
    """Boş liste: bütün kilitler tutuluyor. Dolu liste: süre doldu, tutulamayan işler."""
    deadline = now() + wait
    while True:
        held, busy = _try_locks(files)
        if not busy:
            try:
                yield []
            finally:
                _release(held)
            return
        _release(held)
        if now() >= deadline:
            yield busy
            return
        sleep(POLL)


def switch(paths: Yollar, sha: str) -> None:
    """`ln -sfn` ve `mv -T`'nin karşılığı: bağ yeniden adlandırılarak tek adımda çevrilir."""
    temporary = paths.current.with_name(f".current-{sha}")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(os.path.relpath(paths.surumler / sha, paths.current.parent))
    os.replace(temporary, paths.current)


def _unit_state(runner: Calistirici, unit: str) -> dict[str, str]:
    shown = runner(["systemctl", "show", "-p", "MainPID", "-p", "ActiveState", unit])
    return dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)


def _leave(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def restart_web(
    paths: Yollar, runner: Calistirici, *, sleep: Uyku, now: Saat, wait: float = WEB_WAIT
) -> str | None:
    """Root'un parametresiz birimi istek dosyasını görünce web'i yeniden başlatır (K-133); yeni
    bir ana süreç ayağa kalkana kadar beklenir. Sorun yoksa None."""
    before = _unit_state(runner, WEB_UNIT).get("MainPID", "")
    _leave(paths.web_istek)
    deadline = now() + wait
    while True:
        sleep(POLL)
        state = _unit_state(runner, WEB_UNIT)
        pid = state.get("MainPID", "0")
        if pid not in {"", "0", before} and state.get("ActiveState") == "active":
            return None
        if now() >= deadline:
            return f"web {round(wait)} saniyede yeniden başlamadı"


def run_health_unit(
    paths: Yollar, *, sleep: Uyku, now: Saat, wait: float = HEALTH_WAIT
) -> str | None:
    """`doctor` ayrı ve ağsız bir birimde, işlerle aynı kimlik bilgileriyle çalışır (K-133);
    çalıştırıcı sırları görmez. Birim sonucunu (`$SERVICE_RESULT`) dosyaya yazar."""
    result, output = paths.saglik / "sonuc", paths.saglik / "doctor.txt"
    result.unlink(missing_ok=True)
    output.unlink(missing_ok=True)
    _leave(paths.saglik / "istek")
    deadline = now() + wait
    while not result.exists():
        if now() >= deadline:
            return (
                f"sağlık birimi {round(wait / 60)} dakikada sonuç vermedi "
                f"(`journalctl -u {HEALTH_UNIT}`)"
            )
        sleep(POLL)
    if result.read_text(encoding="utf-8").strip() == "success":
        return None
    try:
        lines = output.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    failures = [line.strip() for line in lines if line.lstrip().startswith("✗")]
    return f"doctor: {'; '.join(failures) if failures else 'başarısız'}"


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: Path, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(self.timeout)
            connection.connect(str(self._path))
        except OSError:
            # Web açılana kadar her denemede yeni soket açılır; bırakılanlar birikmesin.
            connection.close()
            raise
        self.sock = connection


def page_status(path: Path, page: str, login: str, timeout: float = 10) -> int:
    connection = _UnixHTTPConnection(path, timeout)
    try:
        connection.request("GET", page, headers={"Tailscale-User-Login": login})
        return connection.getresponse().status
    finally:
        connection.close()


def check_pages(
    paths: Yollar, login: str, *, sleep: Uyku, now: Saat, wait: float = PAGE_WAIT
) -> str | None:
    """Web yeni süreçle soketi açana kadar kısa bir süre denenir; iki profilin özeti 200 olmalı."""
    if not login:
        return "FT_WEB_ALLOWED_LOGIN tanımlı değil; web denetlenemedi"
    deadline = now() + wait
    for page in PAGES:
        while True:
            try:
                status = page_status(paths.soket, page, login)
            except OSError:
                status = 0
            if status == 200:
                break
            if now() >= deadline:
                shown = status if status else "yanıt yok"
                return f"web {page} için {shown} döndü"
            sleep(POLL)
    return None


def health(paths: Yollar, login: str, *, sleep: Uyku, now: Saat) -> str | None:
    problem = run_health_unit(paths, sleep=sleep, now=now)
    return problem or check_pages(paths, login, sleep=sleep, now=now)


def prune(paths: Yollar, keep: set[str], runner: Calistirici = run) -> None:
    """Son üç sürüm (kurulma sırasıyla) ve `keep` kalır; gerisi silinir."""
    releases = sorted(
        (entry for entry in paths.surumler.iterdir() if SHA.fullmatch(entry.name)),
        key=lambda entry: entry.lstat().st_mtime,
        reverse=True,
    )
    kept = {entry.name for entry in releases[:KEEP_RELEASES]} | keep
    for entry in releases:
        if entry.name not in kept:
            discard(paths, entry, runner)


def subject(paths: Yollar, sha: str, runner: Calistirici = run) -> str:
    shown = _git(paths, runner, "log", "-1", "--format=%s", sha)
    return shown.stdout.strip() if shown.returncode == 0 else ""


@dataclass(frozen=True)
class Ortam:
    """Testlerde değişen dış dünya: komutlar, saat, uyku, bugünün tarihi ve web girişi."""

    runner: Calistirici
    sleep: Uyku
    now: Saat
    today: date
    login: str


def _switch_and_restart(paths: Yollar, sha: str, env: Ortam, *, force: bool) -> str | None:
    """Geçiş iki profilin iş kilitleri tutularak yapılır. `force`: geri dönüşte iş bitmese de
    çevrilir; bozuk sürümde kalmak daha kötüdür."""
    with job_locks(lock_files(paths), wait=LOCK_WAIT, sleep=env.sleep, now=env.now) as busy:
        if busy and not force:
            return f"meşgul: {', '.join(busy)}"
        switch(paths, sha)
        return restart_web(paths, env.runner, sleep=env.sleep, now=env.now)


def deploy(paths: Yollar, sha: str, env: Ortam) -> Sonuc:
    frozen = freeze(paths, env.today)
    if frozen is not None:
        return Sonuc(Kod.TAMAM, frozen_message(frozen, sha), sha, installed(paths))
    current = verify(paths, sha, env.runner)
    release = prepare(paths, sha, current, env.runner)
    reasons = manual_reasons(paths, release, paths.surumler / current)
    if reasons:
        discard(paths, release, env.runner)
        return Sonuc(Kod.ELLE_KURULUM, manual_message(reasons, sha), sha, current)
    timer = upcoming_timer(env.runner, env.now())
    if timer is not None:
        discard(paths, release, env.runner)
        name, moment = timer
        at = datetime.fromtimestamp(moment, ISTANBUL).strftime("%H:%M")
        message = (
            f"⏳ Pencere dışı: {name} {at} (İstanbul) çalışacak; deploy yapılmadı, "
            "sonra yeniden çalıştır."
        )
        return Sonuc(Kod.MESGUL, message, sha, current)
    try:
        problem = _switch_and_restart(paths, sha, env, force=False)
    except OSError as exc:
        problem = f"geçiş yapılamadı ({type(exc).__name__})"
    if problem is not None and problem.startswith("meşgul: ") and installed(paths) == current:
        discard(paths, release, env.runner)
        message = (
            f"⏳ Çalışan iş 10 dakikada bitmedi ({problem[8:]}); deploy yapılmadı, "
            "yeniden çalıştır."
        )
        return Sonuc(Kod.MESGUL, message, sha, current)
    if problem is None:
        problem = health(paths, env.login, sleep=env.sleep, now=env.now)
    if problem is None:
        prune(paths, {sha, current}, env.runner)
        title = subject(paths, sha, env.runner)
        message = f"✅ finans güncellendi: {short(sha)} {title} (önceki {short(current)})."
        return Sonuc(Kod.TAMAM, message.replace("  ", " "), sha, current)
    return rollback(paths, sha, current, problem, env)


def rollback(paths: Yollar, sha: str, previous: str, problem: str, env: Ortam) -> Sonuc:
    try:
        again = _switch_and_restart(paths, previous, env, force=True)
    except OSError as exc:
        again = f"geri geçiş yapılamadı ({type(exc).__name__})"
    if again is None:
        again = health(paths, env.login, sleep=env.sleep, now=env.now)
    if again is None:
        message = (
            f"❌ finans güncellemesi başarısız: {problem}. {short(previous)} sürümüne geri dönüldü."
        )
        return Sonuc(Kod.BASARISIZ, message, sha, previous)
    message = f"🚨 Geri dönüş başarısız, elle müdahale gerekiyor: {problem}; geri dönüşte: {again}."
    return Sonuc(Kod.BASARISIZ, message, sha, previous)


@contextmanager
def runner_lock(paths: Yollar) -> Iterator[None]:
    """`istek` bu kilit tutulurken yeni isteği meşgul diye reddeder."""
    descriptor = os.open(paths.sonuc / "kur.lock", os.O_RDWR | os.O_CREAT, 0o640)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def main(
    paths: Yollar = URETIM,
    env: Ortam | None = None,
    notify: Callable[[Sonuc], None] = lambda _result: None,
) -> int:
    env = env or Ortam(
        run,
        time.sleep,
        time.time,
        today_in_istanbul(),
        os.environ.get("FT_WEB_ALLOWED_LOGIN", ""),
    )
    with runner_lock(paths):
        request = read_request(paths)
        if request is None:
            return int(Kod.TAMAM)
        sha, ident = request
        try:
            result = deploy(paths, sha, env)
        except Durdur as stopped:
            result = stopped.sonuc
        write_result(paths, ident, result, datetime.fromtimestamp(env.now(), ISTANBUL))
    notify(result)
    return int(result.kod)


if __name__ == "__main__":
    sys.exit(main())
