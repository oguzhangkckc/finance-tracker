"""Deploy betiklerinin testleri (K-133): gerçek git depoları, üretimdeki dizin düzeni ve sahte `uv`.
finans paketi import edilmez; CI'da Python 3.12 ile de çalışır. Kullanıcının git ayarları (imza,
kancalar) karışmasın diye HOME ve global ayar yalıtılır."""

import os
import shutil
import subprocess
from dataclasses import dataclass
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
def pi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pi:
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
    for name in ("istek", "sonuc", "uv-cache"):
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
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(0o755)
    uv_log = tmp_path / "uv.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_UV_LOG", str(uv_log))
    monkeypatch.delenv("FAKE_UV_FAIL", raising=False)
    machine = Pi(origin, paths, uv_log)
    machine.install(git("rev-parse", "HEAD", cwd=origin))
    return machine
