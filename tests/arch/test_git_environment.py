import os
import subprocess

from tests.conftest import GIT_LOCAL_ENV


def test_repository_local_git_variables_never_reach_the_tests() -> None:
    listed = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],  # noqa: S607 - git PATH'ten, sabit argüman
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert set(listed) <= set(GIT_LOCAL_ENV)
    assert [name for name in GIT_LOCAL_ENV if name in os.environ] == []
