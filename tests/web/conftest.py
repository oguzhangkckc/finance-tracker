from pathlib import Path

import pytest

from tests.support.web_writes import Site, make_site


@pytest.fixture
def site(tmp_path: Path, migrated_db: Path) -> Site:
    return make_site(tmp_path, migrated_db)
