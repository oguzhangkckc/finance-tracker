from dataclasses import dataclass, field
from datetime import date

from finans.domain.models import CpiPoint, Instrument, PricePoint, YearMonth
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


@dataclass
class FakePriceSource:
    results: dict[str, FetchResult[PricePoint] | SourceError] = field(default_factory=dict)
    calls: list[tuple[str, date, date]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    name: str = "tefas"

    def fetch(self, inst: Instrument, start: date, end: date) -> FetchResult[PricePoint]:
        self.calls.append((inst.code, start, end))
        self.events.append(f"fetch:{inst.code}")
        result = self.results.get(inst.code, FetchResult([], []))
        if isinstance(result, SourceError):
            raise result
        return result
