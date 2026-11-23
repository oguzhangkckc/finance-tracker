from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from finans.domain.models import CpiPoint, DomainError, YearMonth
from finans.domain.numeric import in_domain_context


class CpiSeries:
    def __init__(self, points: Iterable[CpiPoint]) -> None:
        values: dict[YearMonth, Decimal] = {}
        for point in points:
            if point.period in values:
                raise DomainError(f"TÜFE serisinde {point.period} dönemi iki kez var")
            values[point.period] = point.index
        if not values:
            raise DomainError("TÜFE serisi boş")
        self._values = dict(sorted(values.items()))

    def periods(self) -> tuple[YearMonth, ...]:
        return tuple(self._values)

    def earliest(self) -> YearMonth:
        return next(iter(self._values))

    def latest(self) -> YearMonth:
        return next(reversed(self._values))

    def index(self, period: YearMonth) -> Decimal:
        try:
            return self._values[period]
        except KeyError:
            raise DomainError(f"{period} dönemi için TÜFE endeksi yok") from None

    def __contains__(self, period: object) -> bool:
        return period in self._values


@in_domain_context
def chain_link(old: CpiSeries, new: CpiSeries, *, link: YearMonth) -> CpiSeries:
    factor = new.index(link) / old.index(link)
    points = [CpiPoint(p, old.index(p) * factor) for p in old.periods() if p < link]
    points += [CpiPoint(p, new.index(p)) for p in new.periods() if p >= link]
    return CpiSeries(points)


@in_domain_context
def reference_period(day: date, series: CpiSeries) -> YearMonth:
    period = min(YearMonth.of(day).previous(), series.latest())
    if period < series.earliest():
        raise DomainError(
            f"{day} için TÜFE referans dönemi ({period}) serinin başlangıcından "
            f"({series.earliest()}) önce"
        )
    return period


@in_domain_context
def deflator(series: CpiSeries, *, flow_date: date, on: date) -> Decimal:
    return series.index(reference_period(on, series)) / series.index(
        reference_period(flow_date, series)
    )


@in_domain_context
def annual_inflation(series: CpiSeries, period: YearMonth) -> Decimal:
    return series.index(period) / series.index(period.shift(-12)) - 1


@in_domain_context
def fisher_real(nominal: Decimal, inflation: Decimal) -> Decimal:
    return (1 + nominal) / (1 + inflation) - 1
