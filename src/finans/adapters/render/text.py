"""Raporun düz metni; bölümler boş satırla ayrılır, Telegram uzun mesajı bu sınırlardan böler."""

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from finans.contracts.report import (
    AlertLine,
    DataIssueLine,
    HoldingLine,
    PaydayPlan,
    Report,
    ReturnFigure,
)
from finans.domain.numeric import canonical_text
from finans.ports.clock import BUSINESS_TZ

_TITLES = {"weekly": "Haftalık rapor", "monthly": "Aylık rapor"}
_PERIOD_NOTE = (
    "Alım ve satışların tarihi ve tutarı hesaba katılarak, ilk yatırımdan değerleme tarihine "
    "kadarki getiri; bir yıldan kısa dönemde yıllığa çevrilmez."
)


def _digits(value: Decimal, places: int) -> tuple[str, str]:
    """Banker yuvarlaması; binlik ayırıcı nokta, ondalık ayırıcı virgül."""
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
    integer, _, fraction = f"{abs(rounded):f}".partition(".")
    text = f"{int(integer):,}".replace(",", ".") + (f",{fraction}" if places else "")
    sign = "-" if rounded < 0 else ("+" if rounded > 0 else "")
    return sign, text


def money(value: Decimal) -> str:
    sign, text = _digits(value, 2)
    return f"{'-' if sign == '-' else ''}{text} TL"


def percent(rate: Decimal, *, places: int = 2, signed: bool = False) -> str:
    sign, text = _digits(rate * 100, places)
    return f"{sign if signed or sign == '-' else ''}%{text}"


def points(deviation: Decimal) -> str:
    sign, text = _digits(deviation * 100, 1)
    return f"{sign}{text} puan"


def _local(moment: datetime | None) -> str:
    return "yok" if moment is None else f"{moment.astimezone(BUSINESS_TZ):%Y-%m-%d %H:%M}"


class TextRenderer:
    """`hide_amounts` TL tutarlarını gizler (K-90); maaş günü mesajının ayarı ayrıdır (K-93)."""

    def __init__(self, *, hide_amounts: bool = False, payday_amounts: bool = True) -> None:
        self._hide = hide_amounts
        self._payday_amounts = payday_amounts

    def report(self, report: Report) -> str:
        sections = [self._summary(report), self._holdings(report), self._allocation(report)]
        if report.kind == "monthly":
            sections += [self._returns(report), self._lots(report), self._rebalance(report)]
        sections += [_alerts(report.alerts), _issues(report.data_issues), _health(report)]
        return "\n\n".join(sections)

    def payday(self, plan: PaydayPlan) -> str:
        lines = [f"Maaş günü ({plan.logical_date})"]
        if not plan.contribution:
            return "\n".join([*lines, "Bu ay katkı 0."])
        show = self._payday_amounts
        lines.append(
            f"Bu ayki katkı: {money(plan.contribution)}" if show else "Bu ayki katkının dağılımı:"
        )
        for line in plan.lines:
            share = percent(line.share, places=1)
            amount = f"{money(line.amount)} ({share})" if show else f"katkının {share}"
            lines.append(f"{line.asset_class} {line.instrument}: {amount}")
        lines.append("Alımları `ft tx add` ile gir.")
        return "\n".join(lines)

    def _summary(self, report: Report) -> str:
        summary = report.summary
        values = summary.values
        lines = [f"{_TITLES[report.kind]} ({report.logical_date})"]
        if values.total <= 0:
            lines.append("Toplam değer yok.")
        elif self._hide:
            inside = percent(values.in_allocation / values.total, places=1)
            outside = percent(values.out_of_allocation / values.total, places=1)
            lines.append(f"Dağılım içi {inside}, dağılım dışı {outside} (toplam değerin yüzdesi)")
        else:
            lines.append(
                f"Toplam değer: {money(values.total)} (dağılım içi {money(values.in_allocation)},"
                f" dağılım dışı {money(values.out_of_allocation)})"
            )
        change = (
            "önceki hafta için değerleme yok"
            if summary.weekly_change is None
            else f"{percent(summary.weekly_change, signed=True)} (alım ve satışlar hariç)"
        )
        lines.append(f"Haftalık değişim: {change}")
        simple = (
            "hesaplanamadı" if summary.simple_return is None else percent(summary.simple_return)
        )
        lines.append(f"Basit getiri: {simple}")
        if not self._hide:
            lines.append(f"Gerçekleşmiş K/Z: {money(summary.realized_pnl)}")
        return "\n".join(lines)

    def _holdings(self, report: Report) -> str:
        lines = ["Varlıklar"]
        if not report.holdings:
            lines.append("Pozisyon yok.")
        lines += [self._holding(h, report.summary.values.total) for h in report.holdings]
        return "\n".join(lines)

    def _holding(self, holding: HoldingLine, total: Decimal) -> str:
        label = f"{holding.instrument} {holding.asset_class}"
        if not holding.allocation:
            label += " (dağılım dışı)"
        if holding.value is None:
            return f"{label}: fiyat yok"
        worth = (
            f"toplamın {percent(holding.value / total, places=1)}"
            if self._hide
            else money(holding.value)
        )
        parts = [worth, f"fiyat {holding.price_date} ({holding.source})"]
        if holding.simple_return is not None:
            parts.append(f"getiri {percent(holding.simple_return)}")
        if holding.real_return is not None:
            parts.append(f"reel {percent(holding.real_return)}")
        return f"{label}: {', '.join(parts)}"

    def _allocation(self, report: Report) -> str:
        lines = ["Dağılım"]
        if not report.allocation:
            lines.append("Dağılım içi değer yok.")
        for line in report.allocation:
            worth = "" if self._hide else f"{money(line.value)}, "
            lines.append(
                f"{line.asset_class}: {worth}{percent(line.weight, places=1)}"
                f" (hedef {percent(line.target, places=1)}, sapma {points(line.deviation)})"
            )
        if report.quiet_period:
            lines.append("Portföy henüz küçük; sapma alarmları 3 aylık katkıya ulaşınca başlar.")
        return "\n".join(lines)

    def _returns(self, report: Report) -> str:
        summary = report.summary
        lines = ["Getiri (dağılım içi)"]
        lines += _figure(summary.money_weighted, real=False)
        if summary.real_money_weighted is None:
            lines.append("Reel para ağırlıklı getiri: TÜFE verisi yok")
        else:
            lines += _figure(summary.real_money_weighted, real=True)
        figure = summary.money_weighted
        if figure is not None and figure.status == "ok" and not figure.annualized:
            lines.append(_PERIOD_NOTE)
        inflation = report.inflation
        if inflation is None:
            lines.append("Enflasyon: TÜFE verisi yok")
        elif inflation.annual_inflation is None:
            lines.append(f"Enflasyon: TÜFE {inflation.valuation_period}, yıllık hesaplanamadı")
        else:
            annual = percent(inflation.annual_inflation)
            lines.append(f"Enflasyon: TÜFE {inflation.valuation_period}, yıllık {annual}")
        return "\n".join(lines)

    def _lots(self, report: Report) -> str:
        lines = ["Lotlar"]
        if not report.lots:
            lines.append("Lot yok.")
        for lot in report.lots:
            real = "hesaplanamadı" if lot.real_return is None else percent(lot.real_return)
            period = "" if lot.cpi_period is None else f" (TÜFE {lot.cpi_period})"
            if self._hide:
                lines.append(f"{lot.instrument} {lot.acquired}: reel {real}{period}")
                continue
            value = "fiyat yok" if lot.value is None else money(lot.value)
            lines.append(
                f"{lot.instrument} {lot.acquired}: {canonical_text(lot.units)} adet,"
                f" maliyet {money(lot.cost)}, değer {value}, reel {real}{period}"
            )
        return "\n".join(lines)

    def _rebalance(self, report: Report) -> str:
        lines = ["Katkıyla dengeleme"]
        plan = report.rebalance
        if plan is None:
            lines.append("Katkı tanımlı değil.")
        elif not plan.lines:
            lines.append("Bu ay katkı 0.")
        else:
            if not self._hide:
                lines.append(f"Bu ayki katkı: {money(plan.contribution)}")
            for line in plan.lines:
                share = percent(line.amount / plan.contribution, places=1)
                amount = f"katkının {share}" if self._hide else money(line.amount)
                lines.append(f"{line.asset_class} {line.instrument}: {amount}")
        return "\n".join(lines)


def _figure(figure: ReturnFigure | None, *, real: bool) -> list[str]:
    if figure is None or figure.rate is None:
        if real or figure is None:
            return []
        if figure.status == "out_of_range":
            return ["Zamanlama nedeniyle para ağırlıklı getiri anlamlı değil."]
        return ["Para ağırlıklı getiri: hesaplanamadı"]
    rate = percent(figure.rate)
    if figure.annualized:
        label = "Reel XIRR" if real else "Yıllık para ağırlıklı getiri (XIRR)"
    else:
        label = (
            "Reel dönem getirisi (para ağırlıklı, yıllık değil)"
            if real
            else "Dönem getirisi (para ağırlıklı, yıllık değil)"
        )
    return [f"{label}: {rate}"]


def _alerts(alerts: list[AlertLine]) -> str:
    lines = ["Açık uyarılar"]
    if not alerts:
        lines.append("Açık uyarı yok.")
    for alert in alerts:
        side = "üstünde" if alert.direction == "above" else "altında"
        gap = "" if alert.deviation is None else f", sapma {points(alert.deviation)}"
        lines.append(f"{alert.asset_class}: hedefin {side}{gap} (açılış {_local(alert.opened_at)})")
    return "\n".join(lines)


def _issues(issues: list[DataIssueLine]) -> str:
    lines = ["Veri sorunları"]
    if not issues:
        lines.append("Veri sorunu yok.")
    for issue in issues:
        where = " ".join(str(part) for part in (issue.instrument, issue.day) if part is not None)
        mark = "!" if issue.level == "warn" else "i"
        lines.append(f"{mark} {issue.check}{' ' + where if where else ''}: {issue.message}")
    return "\n".join(lines)


def _health(report: Report) -> str:
    health = report.health
    return (
        f"Sistem: son fiyat senkronu {_local(health.last_price_sync)},"
        f" son TÜFE senkronu {_local(health.last_cpi_sync)},"
        f" son 7 günde başarısız iş {health.failed_jobs_7d}"
    )
