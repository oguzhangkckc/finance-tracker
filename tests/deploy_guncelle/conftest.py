"""finans-guncelle testleri (K-140): gerçek git depoları, kurulu kopyalar; `runuser`, `systemctl`,
`systemd-run`, `uv` ve `curl` sahtedir.
finans paketi import edilmez; CI'da Python 3.12 ile de çalışır. Kullanıcının git ayarları (imza,
kancalar) karışmasın diye HOME ve global ayar yalıtılır."""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import guncelle

FILES = {
    "deploy/systemd/finans-web.service": "[Service]\nExecStart=/opt/finans/.venv/bin/finans-web\n",
    "deploy/systemd/finans-web.service.d/profil.conf": "[Service]\nEnvironment=FT_PROFILE=sanal\n",
    "deploy/systemd/finans-backup.timer": "[Timer]\nOnCalendar=*-*-* 03:00\n",
    "deploy/ft-finans": "#!/bin/sh\n# ft-finans\n",
    "deploy/ft-sanal": "#!/bin/sh\n# ft-sanal\n",
    "deploy/guncelle.py": "# guncelle\n",
    "src/finans/adapters/sqlite/migrations/0001_init.sql": "CREATE TABLE t (x TEXT);\n",
    "docs/DESIGN.md": "tasarım\n",
}
FAKE_RUNUSER = """#!/bin/sh
if [ "$1" != "-u" ] || [ "$3" != "--" ]; then exit 99; fi
printf '%s %s\\n' "$2" "$4" >> "$FAKE_RUNUSER_LOG"
shift 3
exec "$@"
"""
# Tek betik dört komutun yerine geçer; adı (`argv[0]`) hangisi olduğunu söyler. Davranışı
# FAKE_STATE dizinindeki config.json belirler, her çağrı calls.jsonl'a yazılır.
FAKE_COMMANDS = ("systemctl", "systemd-run", "uv", "curl")
FAKE_BODY = """
import json, os, sys
from pathlib import Path
state = Path(os.environ["FAKE_STATE"])
name = Path(sys.argv[0]).name
args = sys.argv[1:]
config = json.loads((state / "config.json").read_text(encoding="utf-8"))
call = {"name": name, "args": args, "uv_python": os.environ.get("UV_PYTHON_INSTALL_DIR")}
with (state / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps(call, ensure_ascii=False) + "\\n")
def save():
    (state / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
if name == "systemctl":
    if args[0] == "list-units":
        if config["list_units_exit"]:
            sys.exit(config["list_units_exit"])
        for unit in config["jobs"]:
            print(unit + " loaded active running İş")
    elif args[0] == "show":
        print("MainPID=" + str(config["web"]["pid"]))
        print("ActiveState=" + config["web"]["state"])
    elif args[0] == "restart":
        if config["restart_exit"]:
            print("Job for finans-web.service failed.", file=sys.stderr)
            sys.exit(config["restart_exit"])
        if not config["web_stays"]:
            config["web"]["pid"] += 1
            save()
    sys.exit(0)
if name == "systemd-run":
    profile = "sanal" if "Environment=FT_PROFILE=sanal" in args else "gercek"
    ft = next(index for index, arg in enumerate(args) if arg.endswith("/.venv/bin/ft"))
    command = " ".join(args[ft + 1:])
    if command == "doctor":
        sys.stdout.write(config["doctor"][profile]["out"])
        sys.exit(config["doctor"][profile]["exit"])
    if command == "db migrate":
        sys.exit(config["migrate_exit"][profile])
    if command == "backup verify":
        sys.exit(config["verify_exit"][profile])
    sys.exit(97)
if name == "uv":
    if config["uv_fail"] > 0:
        config["uv_fail"] -= 1
        save()
        print("error: uv.lock güncel değil", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)
if name == "curl":
    sys.exit(config["curl_exit"])
sys.exit(98)
"""
CONFIG: dict[str, Any] = {
    "jobs": [],
    "list_units_exit": 0,
    "web": {"pid": 100, "state": "active"},
    "restart_exit": 0,
    "web_stays": False,
    "doctor": {
        "gercek": {"out": "✓ Veritabanı şeması: güncel\n", "exit": 0},
        "sanal": {"out": "✓ Veritabanı şeması: güncel\n", "exit": 0},
    },
    "migrate_exit": {"gercek": 0, "sanal": 0},
    "verify_exit": {"gercek": 0, "sanal": 0},
    "uv_fail": 0,
    "curl_exit": 0,
}
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
    paths: guncelle.Yollar
    log: Path
    state: Path

    def commit(self, files: dict[str, str | None], branch: str = "main") -> str:
        """`None` dosyayı siler. Başka daldaki commit'ten sonra `main`'e dönülür."""
        if branch != "main":
            git("checkout", "-q", "-B", branch, cwd=self.origin)
        for name, content in files.items():
            path = self.origin / name
            if content is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        git("add", "-A", cwd=self.origin)
        git("commit", "-q", "-m", f"değişiklik ({branch})", cwd=self.origin)
        sha = git("rev-parse", "HEAD", cwd=self.origin)
        if branch != "main":
            git("checkout", "-q", "main", cwd=self.origin)
        return sha

    def install(self, sha: str) -> None:
        """Elle kurulumun sonucu: depo o commit'te, birim ve betik kopyaları ondan."""
        paths = self.paths
        git("fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*", cwd=paths.repo)
        git("checkout", "-q", "-B", "main", sha, cwd=paths.repo)
        if paths.systemd.exists():
            shutil.rmtree(paths.systemd)
        shutil.copytree(paths.repo / guncelle.UNITS, paths.systemd)
        paths.betikler.mkdir(exist_ok=True)
        for name, source in guncelle.WRAPPERS.items():
            shutil.copyfile(paths.repo / source, paths.betikler / name)
        shutil.copyfile(paths.repo / guncelle.SELF, paths.betik)

    def fetch(self) -> None:
        """`verify`'ın yaptığı çekme; elle kurulum kurallarını tek başına sınamak için."""
        git("fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*", cwd=self.paths.repo)

    def head(self) -> str:
        return git("rev-parse", "HEAD", cwd=self.paths.repo)

    def config(self, **changes: Any) -> None:
        path = self.state / "config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config.update(changes)
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    def calls(self, name: str | None = None) -> list[list[str]]:
        """Sahte komutların argümanları, çağrı sırasıyla; `name` verilirse yalnız o komut."""
        path = self.state / "calls.jsonl"
        if not path.exists():
            return []
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return [
            [record["name"], *record["args"]]
            for record in records
            if name in (None, record["name"])
        ]

    def uv_python(self) -> list[str | None]:
        path = self.state / "calls.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return [record["uv_python"] for record in records if record["name"] == "uv"]

    def env(self, **values: str) -> None:
        """finans.env'e satır ekler (FT_BACKUP_DIR fixture'da yazılıdır)."""
        with self.paths.finans_env.open("a", encoding="utf-8") as env_file:
            for key, value in values.items():
                env_file.write(f"{key}={value}\n")

    def backup(self, prefix: str, age: float) -> Path:
        directory = self.paths.veri / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{prefix}20261216T030000Z.db.age"
        path.write_bytes(b"age")
        os.utime(path, (NOW - age, NOW - age))
        return path

    def users(self) -> list[str]:
        """Sahte `runuser`'ın kaydı: her satır `<kullanıcı> <komut>`."""
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def pi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pi:
    home = tmp_path / "home"
    home.mkdir()
    isolation = {
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    for name, value in {
        **isolation,
        "GIT_AUTHOR_NAME": "Deneme",
        "GIT_AUTHOR_EMAIL": "deneme@example.com",
        "GIT_COMMITTER_NAME": "Deneme",
        "GIT_COMMITTER_EMAIL": "deneme@example.com",
    }.items():
        monkeypatch.setenv(name, value)
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    for name, content in FILES.items():
        path = origin / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=origin)
    git("commit", "-q", "-m", "ilk", cwd=origin)
    repo = tmp_path / "opt-finans"
    git("clone", "-q", str(origin), str(repo), cwd=tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    runuser = bin_dir / "runuser"
    runuser.write_text(FAKE_RUNUSER, encoding="utf-8")
    runuser.chmod(0o755)
    for name in FAKE_COMMANDS:
        fake = bin_dir / name
        fake.write_text(f"#!{sys.executable}{FAKE_BODY}", encoding="utf-8")
        fake.chmod(0o755)
    log = tmp_path / "runuser.log"
    state = tmp_path / "fake-state"
    state.mkdir()
    (state / "config.json").write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
    veri = tmp_path / "var-lib-finans"
    veri.mkdir()
    betikler = tmp_path / "usr-local-sbin"
    paths = guncelle.Yollar(
        repo=repo,
        systemd=tmp_path / "etc-systemd-system",
        betikler=betikler,
        betik=betikler / "finans-guncelle",
        finans_env=tmp_path / "finans.env",
        kilit=tmp_path / "finans-guncelle.lock",
        python=repo / ".python",
        on_yuz=repo / "frontend" / "dist",
        credstore=tmp_path / "credstore",
        veri=veri,
        sistem_python=sys.executable,
        kullanici="finans",
        ortam={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "LANG": "C.UTF-8",
            "FAKE_RUNUSER_LOG": str(log),
            "FAKE_STATE": str(state),
            **isolation,
        },
    )
    paths.credstore.mkdir()
    machine = Pi(origin, paths, log, state)
    machine.install(git("rev-parse", "HEAD", cwd=origin))
    machine.env(FT_BACKUP_DIR=str(veri / "backups"))
    machine.backup("finans-", age=3600)
    machine.backup("sanal-", age=3600)
    return machine


@dataclass
class Saat:
    """Testin saati ve uyku fonksiyonu; `after` ile belli bir süre sonra durum değiştirilir."""

    clock: float = NOW
    hooks: list[tuple[float, Callable[[], None]]] = field(default_factory=list)

    def now(self) -> float:
        return self.clock

    def sleep(self, seconds: float) -> None:
        self.clock += seconds
        for at, hook in list(self.hooks):
            if self.clock >= at:
                self.hooks.remove((at, hook))
                hook()

    def after(self, seconds: float, hook: Callable[[], None]) -> None:
        self.hooks.append((self.clock + seconds, hook))


@pytest.fixture
def saat() -> Saat:
    return Saat()


@pytest.fixture
def ortam(saat: Saat) -> guncelle.Ortam:
    return guncelle.Ortam(guncelle.run, saat.sleep, saat.now)
