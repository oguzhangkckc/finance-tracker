"""Deploy betiklerinin testleri (K-133): gerçek git depoları, üretimdeki dizin düzeni ve sahte `uv`.
finans paketi import edilmez; CI'da Python 3.12 ile de çalışır. Kullanıcının git ayarları (imza,
kancalar) karışmasın diye HOME ve global ayar yalıtılır."""

import fcntl
import http.server
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import kur

FILES = {
    "deploy/systemd/finans-web.service": "[Service]\nExecStart=/opt/finans/current/web\n",
    "deploy/systemd/finans-web.service.d/profil.conf": "[Service]\nEnvironment=FT_PROFILE=sanal\n",
    "deploy/systemd/finans-backup.timer": "[Timer]\nOnCalendar=*-*-* 03:00\n",
    "deploy/ci/istek.py": "# istek\n",
    "deploy/ci/kur.py": "# kur\n",
    "src/finans/adapters/sqlite/migrations/0001_init.sql": "CREATE TABLE t (x TEXT);\n",
    "docs/DESIGN.md": "tasarım\n",
}
FAKE_UV = """#!/bin/sh
printf '%s|%s|%s|%s\\n' "$PWD" "$*" "$UV_PYTHON_INSTALL_DIR" "$UV_CACHE_DIR" >> "$FAKE_UV_LOG"
if [ -n "$FAKE_UV_FAIL" ]; then
  echo "uv: uv.lock güncel değil" >&2
  exit 2
fi
mkdir -p .venv/bin
"""
FAKE_SYSTEMCTL = """#!/bin/sh
case "$*" in
  *finans-web.service*) cat "$FAKE_SYSTEMD_WEB" ;;
  *"finans-*.timer"*)
    if [ -f "$FAKE_SYSTEMD_TIMERS_FAIL" ]; then exit 1; fi
    cat "$FAKE_SYSTEMD_TIMERS" ;;
  *) exit 1 ;;
esac
"""
LOGIN = "kisi@example.com"
NOW = 1_797_000_000.0


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(  # noqa: S603 - testin yerel git deposu
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@dataclass
class Pi:
    origin: Path
    paths: kur.Yollar
    uv_log: Path

    def commit(self, files: dict[str, str | None], branch: str = "main") -> str:
        """`None` dosyayı siler. Başka daldaki commit'ten sonra `main`'e dönülür."""
        if branch != "main":
            git("checkout", "-q", "-B", branch, cwd=self.origin)
        for name, text in files.items():
            path = self.origin / name
            if text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        git("add", "-A", cwd=self.origin)
        git("commit", "-q", "-m", f"değişiklik ({branch})", cwd=self.origin)
        sha = git("rev-parse", "HEAD", cwd=self.origin)
        if branch != "main":
            git("checkout", "-q", "main", cwd=self.origin)
        return sha

    def install(self, sha: str) -> Path:
        """Elle kurulumun sonucu: sürüm dizini, `current` ve kurulu birim ve betik kopyaları."""
        paths = self.paths
        git("fetch", "-q", "origin", "+refs/heads/*:refs/heads/*", cwd=paths.repo)
        release = paths.surumler / sha
        if not release.exists():
            git("worktree", "add", "-q", "--detach", str(release), sha, cwd=paths.repo)
        if paths.current.is_symlink():
            paths.current.unlink()
        paths.current.symlink_to(Path("releases") / sha)
        if paths.systemd.exists():
            shutil.rmtree(paths.systemd)
        shutil.copytree(release / kur.UNITS, paths.systemd)
        paths.betikler.mkdir(exist_ok=True)
        for name, source in kur.SCRIPTS.items():
            shutil.copyfile(release / source, paths.betikler / name)
        return release

    def worktrees(self) -> list[str]:
        listed = git("worktree", "list", "--porcelain", cwd=self.paths.repo)
        return [
            line.split(" ", 1)[1] for line in listed.splitlines() if line.startswith("worktree ")
        ]


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """macOS'ta Unix soket yolu en çok 104 bayt; pytest'in geçici dizini daha uzun olabilir."""
    path = Path(tempfile.mkdtemp(prefix="fs"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def pi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, short_dir: Path) -> Pi:
    home = tmp_path / "home"
    home.mkdir()
    for name, value in {
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Deneme",
        "GIT_AUTHOR_EMAIL": "deneme@example.com",
        "GIT_COMMITTER_NAME": "Deneme",
        "GIT_COMMITTER_EMAIL": "deneme@example.com",
    }.items():
        monkeypatch.setenv(name, value)
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    for name, text in FILES.items():
        path = origin / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git("add", "-A", cwd=origin)
    git("commit", "-q", "-m", "ilk", cwd=origin)
    opt = tmp_path / "opt"
    opt.mkdir()
    git("clone", "-q", "--bare", str(origin), str(opt / "repo.git"), cwd=tmp_path)
    (opt / "releases").mkdir()
    var = tmp_path / "var"
    for name in ("istek", "sonuc", "uv-cache", "saglik", "locks/sanal"):
        (var / name).mkdir(parents=True)
    paths = kur.Yollar(
        istek=var / "istek" / "deploy.request",
        sonuc=var / "sonuc",
        dondur=tmp_path / "etc" / "deploy-dondur",
        repo=opt / "repo.git",
        surumler=opt / "releases",
        current=opt / "current",
        python=opt / ".python",
        uv_cache=var / "uv-cache",
        systemd=tmp_path / "systemd",
        betikler=tmp_path / "betikler",
        kilitler=(var / "locks", var / "locks" / "sanal"),
        web_istek=var / "web-yeniden-baslat",
        saglik=var / "saglik",
        soket=short_dir / "web.sock",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in (("uv", FAKE_UV), ("systemctl", FAKE_SYSTEMCTL)):
        executable = bin_dir / name
        executable.write_text(script, encoding="utf-8")
        executable.chmod(0o755)
    uv_log = tmp_path / "uv.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_UV_LOG", str(uv_log))
    monkeypatch.delenv("FAKE_UV_FAIL", raising=False)
    machine = Pi(origin, paths, uv_log)
    machine.install(git("rev-parse", "HEAD", cwd=origin))
    return machine


@dataclass
class Systemd:
    """Testin uyku fonksiyonu: saati ilerletir ve istek dosyalarına root birimi ve sağlık birimi
    gibi yanıt verir. Web yeniden başlarken iş kilitlerinin tutulup tutulmadığını kaydeder."""

    paths: kur.Yollar
    web_state: Path
    timers: Path
    clock: float = NOW
    pid: int = 100
    web_restarts: bool = True
    doctor_results: list[str] = field(default_factory=list)
    doctor_output: str = "✓ Veritabanı şeması: güncel\n"
    events: list[tuple[str, str | None, bool]] = field(default_factory=list)

    def now(self) -> float:
        return self.clock

    def sleep(self, seconds: float) -> None:
        self.clock += seconds
        if self.paths.web_istek.exists():
            self.paths.web_istek.unlink()
            self.events.append(("web", kur.installed(self.paths), self._locked()))
            if self.web_restarts:
                self.pid += 1
                self.write_web()
        request = self.paths.saglik / "istek"
        if request.exists():
            request.unlink()
            result = self.doctor_results.pop(0) if self.doctor_results else "success"
            self.events.append(("saglik", kur.installed(self.paths), self._locked()))
            (self.paths.saglik / "doctor.txt").write_text(self.doctor_output, encoding="utf-8")
            (self.paths.saglik / "sonuc").write_text(f"{result}\n", encoding="utf-8")

    def write_web(self) -> None:
        self.web_state.write_text(f"MainPID={self.pid}\nActiveState=active\n", encoding="utf-8")

    def timers_due(self, *entries: tuple[str, float]) -> None:
        blocks = [f"Id={name}\nNextElapseUSecRealtime=@{int(at)}" for name, at in entries]
        self.timers.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

    def _locked(self) -> bool:
        """Bir işin kilidi şu an başkasında mı (geçiş kilitler tutularak mı yapılıyor)."""
        path = self.paths.kilitler[0] / "backup.lock"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(descriptor)
        return False


@pytest.fixture
def systemd(pi: Pi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Systemd:
    machine = Systemd(pi.paths, tmp_path / "web.state", tmp_path / "timers.txt")
    machine.write_web()
    machine.timers_due(("finans-backup.timer", NOW + 24 * 3600))
    monkeypatch.setenv("FAKE_SYSTEMD_WEB", str(machine.web_state))
    monkeypatch.setenv("FAKE_SYSTEMD_TIMERS", str(machine.timers))
    monkeypatch.setenv("FAKE_SYSTEMD_TIMERS_FAIL", str(tmp_path / "timers.fail"))
    return machine


@dataclass
class Web:
    """Unix soketinde web'in yerine geçen küçük sunucu; sayfa başına yanıt kodu değiştirilebilir."""

    statuses: dict[str, int] = field(default_factory=lambda: {"/gercek/": 200, "/sanal/": 200})
    logins: list[str] = field(default_factory=list)


@pytest.fixture
def web(pi: Pi) -> Iterator[Web]:
    state = Web()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            login = self.headers.get("Tailscale-User-Login", "")
            state.logins.append(login)
            status = state.statuses.get(self.path, 404) if login == LOGIN else 403
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

        def address_string(self) -> str:
            return "unix"

    server = socketserver.UnixStreamServer(str(pi.paths.soket), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
