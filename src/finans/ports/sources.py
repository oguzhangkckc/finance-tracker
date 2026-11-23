from pathlib import Path
from typing import Protocol

from finans.domain.portfolio import PortfolioConfig


class PortfolioConfigSource(Protocol):
    def load(self, path: Path) -> PortfolioConfig:
        """Geçersiz dosyada bütün sorunlarla birlikte ConfigError yükseltir."""
        ...
