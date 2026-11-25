"""finans-guncelle testleri (K-140): gerçek git depoları, kurulu kopyalar ve sahte `runuser`.
finans paketi import edilmez; CI'da Python 3.12 ile de çalışır. Kullanıcının git ayarları (imza,
kancalar) karışmasın diye HOME ve global ayar yalıtılır."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

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
    log = tmp_path / "runuser.log"
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
        kullanici="finans",
        ortam={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "LANG": "C.UTF-8",
            "FAKE_RUNUSER_LOG": str(log),
            **isolation,
        },
    )
    machine = Pi(origin, paths, log)
    machine.install(git("rev-parse", "HEAD", cwd=origin))
    return machine
