"""EVDS3 canlı smoke testi: `make live`. CI'da çalışmaz; haftalık timer M4'te."""

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from finans import bootstrap
from finans.adapters.clock import SystemClock
from finans.domain.models import CpiPoint, YearMonth
from finans.ports.sources import CpiSource
from finans.settings import Settings

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
# _isolated_env ortamı test başlamadan temizler; LoadCredential dizini modül yüklenirken alınır.
CREDENTIALS = os.environ.get("CREDENTIALS_DIRECTORY")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    loaded = Settings(
        db_path=tmp_path / "kullanilmaz.db", _env_file=ROOT / ".env", _secrets_dir=CREDENTIALS
    )
    if loaded.evds_api_key is None:
        pytest.skip("FT_EVDS_API_KEY tanımlı değil (.env ya da LoadCredential)")
    return loaded


@pytest.fixture
def evds(settings: Settings) -> Iterator[CpiSource]:
    with bootstrap.cpi_source(settings, SystemClock()) as source:
        yield source


def test_reference_month_keeps_its_published_value(evds: CpiSource, settings: Settings) -> None:
    january = YearMonth(2025, 1)
    result = evds.fetch(settings.cpi_series, january, january)
    assert result.points == [CpiPoint(january, Decimal("88.578291"))]


def test_series_is_still_published(evds: CpiSource, settings: Settings) -> None:
    this_month = YearMonth.of(SystemClock().today())
    result = evds.fetch(settings.cpi_series, this_month.shift(-4), this_month)
    assert result.points, "son dört ayda dönem yok; seri ya da baz yılı değişmiş olabilir"
    assert max(point.period for point in result.points) >= this_month.shift(-2)
