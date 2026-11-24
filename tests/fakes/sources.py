from dataclasses import dataclass, field

from finans.domain.models import CpiPoint, YearMonth
from finans.ports.sources import FetchResult, SourceError


@dataclass
class FakeCpiSource:
    result: FetchResult[CpiPoint] | SourceError
    calls: list[tuple[str, YearMonth, YearMonth]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def fetch(self, series: str, start: YearMonth, end: YearMonth) -> FetchResult[CpiPoint]:
        self.calls.append((series, start, end))
        self.events.append("fetch")
        if isinstance(self.result, SourceError):
            raise self.result
        return self.result
