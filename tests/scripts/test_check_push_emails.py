import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_push_emails.py"
NOREPLY = "1+deneme@users.noreply.github.com"
OTHER = "deneme@example.com"


def _env(**extra: str) -> dict[str, str]:
    # Hook içinden çalışan pytest'te GIT_DIR gibi değişkenler gerçek repoyu gösterebilir.
    clean = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "PRE_COMMIT_"))
    }
    return {**clean, **extra}


def _git(repo: Path, *args: str, author: str = NOREPLY, committer: str | None = None) -> str:
    env = _env(
        GIT_AUTHOR_NAME="Deneme",
        GIT_AUTHOR_EMAIL=author,
        GIT_COMMITTER_NAME="Deneme",
        GIT_COMMITTER_EMAIL=committer or author,
    )
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.strip()


def _commit(
    repo: Path, message: str, *, author: str = NOREPLY, committer: str | None = None
) -> str:
    _git(repo, "commit", "--allow-empty", "-q", "-m", message, author=author, committer=committer)
    return _git(repo, "rev-parse", "--short", "HEAD")


def _check(repo: Path, tip: str = "HEAD") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=_env(PRE_COMMIT_TO_REF=tip),
    )


def _init(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=_env())
    _git(path, "config", "user.email", NOREPLY)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = _init(tmp_path / "repo")
    _commit(path, "yayımlanmış", author=OTHER)
    _git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return path


def test_only_unpublished_commits_are_checked(repo: Path) -> None:
    _commit(repo, "yeni")
    _commit(repo, "eski biçim", author="deneme@users.noreply.github.com")

    result = _check(repo)

    assert result.returncode == 0, result.stdout
    assert result.stdout == ""


def test_other_email_stops_the_push_and_shows_the_fix(repo: Path) -> None:
    _commit(repo, "iyi")
    bad = _commit(repo, "kötü", author=OTHER)

    result = _check(repo)

    assert result.returncode == 1
    assert f"  {bad} (yazar ve committer): kötü" in result.stdout
    assert "1) Bu repodaki user.email zaten noreply; bu adımı atla." in result.stdout
    assert "git rebase --exec 'git commit --amend --no-edit" in result.stdout
    assert f"' {bad}^" in result.stdout
    assert OTHER not in result.stdout


def test_committer_email_is_checked_too(repo: Path) -> None:
    bad = _commit(repo, "committer", committer=OTHER)
    assert f"  {bad} (committer): committer" in _check(repo).stdout


def test_repository_email_that_is_not_noreply_is_flagged_first(repo: Path) -> None:
    _git(repo, "config", "user.email", OTHER)
    _commit(repo, "kötü", author=OTHER)

    result = _check(repo)

    expected = 'git config --local user.email "<id>+<kullanıcı>@users.noreply.github.com"'
    assert expected in result.stdout
    assert OTHER not in result.stdout


def test_root_commit_is_rewritten_from_the_root(tmp_path: Path) -> None:
    repo = _init(tmp_path / "yeni")
    _commit(repo, "ilk", author=OTHER)
    assert "' --root" in _check(repo).stdout


def test_branch_deletion_is_not_checked(repo: Path) -> None:
    _commit(repo, "kötü", author=OTHER)
    assert _check(repo, "0" * 40).returncode == 0
