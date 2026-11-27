"""Deploy testlerinin git komutları yalnız geçici depolara gider: bağlı bir worktree'den gelen
GIT_DIR, `make deploy-py312`'de de testlere ulaşmaz."""

import os

from tests.deploy_guncelle.conftest import GIT_LOCAL_ENV


def test_repository_local_git_variables_never_reach_the_deploy_tests() -> None:
    assert {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"} <= set(GIT_LOCAL_ENV)
    assert [name for name in GIT_LOCAL_ENV if name in os.environ] == []
