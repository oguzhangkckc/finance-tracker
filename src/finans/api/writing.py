"""Yazma uçlarının girdileri ve yanıtları (K-137, K-138).

Girdi kullanıcının yazdığı metindir; ondalık ayırıcı virgüldür, nokta reddedilir (K-126). Kurallar
ve iletiler `sunum.writes`'tadır; burada yalnız JSON alan adları web formununkilere çevrilir. Onay
jetonu (`confirmation`) istemci için opaktır: önizlemenin döndürdüğü sözlük kayıtta aynen geri
gönderilir."""

from collections.abc import Mapping
from datetime import date
from typing import Final, Literal

from pydantic import Field

from finans.api.models import DecimalStr, ErrorBody, Model
from finans.api.pages import RefreshInfo
from finans.application.paper import PaydayPurchasePlan, PaydayStatus
from finans.application.previews import VoidPreview
from finans.ports.repositories import StoredTransaction
from finans.sunum.profiles import ProfileSlug
from finans.sunum.writes import PlannedTrade, TradeKind

TEXT_MAX: Final = 200
# Web formunun alan adı → JSON alan adı; FormErrors'ın alanları istemciye bu adlarla gider.
FIELD_NAMES: Final = {
    "fon": "fund",
    "gun": "day",
    "adet": "units",
    "fiyat": "price",
    "komisyon": "fee",
    "tutar": "amount",
    "tumu": "all",
    "dekont": "ref",
    "gerekce": "reason",
    "maas_gunu": "payday",
    "iptaller": "reapply_voided",
}


def json_fields(fields: Mapping[str, str]) -> dict[str, str]:
    return {FIELD_NAMES.get(name, name): message for name, message in fields.items()}


class TradeInput(Model):
    """Gerçek profilde adet, fiyat, komisyon ve dekont; sanal alımda tutar ve komisyon; sanal
    satışta adet ya da `all`. Profile uymayan alanlar yok sayılır."""

    fund: str = Field(default="", max_length=TEXT_MAX)
    day: str = Field(default="", max_length=TEXT_MAX)
    units: str = Field(default="", max_length=TEXT_MAX)
    price: str = Field(default="", max_length=TEXT_MAX)
    fee: str = Field(default="", max_length=TEXT_MAX)
    amount: str = Field(default="", max_length=TEXT_MAX)
    all: bool = False
    ref: str = Field(default="", max_length=TEXT_MAX)

    def form(self) -> dict[str, str]:
        return {
            "fon": self.fund,
            "gun": self.day,
            "adet": self.units,
            "fiyat": self.price,
            "komisyon": self.fee,
            "tutar": self.amount,
            "tumu": "1" if self.all else "",
            "dekont": self.ref,
        }


class ReasonInput(Model):
    reason: str = Field(default="", max_length=1000)


class PaydayInput(Model):
    payday: str = Field(default="", max_length=TEXT_MAX)
    reapply_voided: bool = False

    def form(self) -> dict[str, str]:
        return {"maas_gunu": self.payday, "iptaller": "1" if self.reapply_voided else ""}


class ConfirmInput(Model):
    confirmation: dict[str, str]


class Saved(Model):
    """`number`: işlem numarası; maaş gününde kaydedilen alım sayısı. `duplicate`: bu onay daha
    önce kullanılmış, yeniden kaydedilmedi; numara ilk kaydınkidir."""

    number: int
    duplicate: bool


class TradeError(ErrorBody):
    """K-109: sanal işlemde o günün fiyatı yoksa en yakın fiyatlı günler; yalnız seçenektir."""

    price_days: list[date] = Field(default_factory=list)


class TradePreviewBody(Model):
    """`changed`: onayda sonuç önizlemeden farklı çıktı, kayıt yapılmadı; bu yeni önizlemedir."""

    profile: ProfileSlug
    kind: TradeKind
    instrument: str
    fund_name: str
    trade_date: date
    side: Literal["BUY", "SELL"]
    units: DecimalStr
    unit_price: DecimalStr
    fee: DecimalStr
    gross: DecimalStr
    ref: str | None
    units_before: DecimalStr
    units_after: DecimalStr
    leftover: DecimalStr | None
    warnings: list[str]
    confirmation: dict[str, str]
    changed: bool


def trade_preview_body(
    profile: ProfileSlug,
    kind: TradeKind,
    planned: PlannedTrade,
    names: Mapping[str, str],
    confirmation: dict[str, str],
    *,
    changed: bool,
) -> TradePreviewBody:
    preview = planned.preview
    tx = preview.transaction
    return TradePreviewBody(
        profile=profile,
        kind=kind,
        instrument=tx.instrument,
        fund_name=names.get(tx.instrument, tx.instrument),
        trade_date=tx.trade_date,
        side=tx.side.value,
        units=tx.units,
        unit_price=tx.unit_price,
        fee=tx.fee,
        gross=preview.gross,
        ref=preview.ref,
        units_before=preview.units_before,
        units_after=preview.units_after,
        leftover=None if planned.paper is None else planned.paper.leftover,
        warnings=[issue.message for issue in preview.warnings],
        confirmation=confirmation,
        changed=changed,
    )


class BlockingSale(Model):
    id: int
    instrument: str
    trade_date: date
    units: DecimalStr


def blocking_sale(stored: StoredTransaction) -> BlockingSale:
    tx = stored.transaction
    return BlockingSale(
        id=stored.id, instrument=tx.instrument, trade_date=tx.trade_date, units=tx.units
    )


class VoidBlocked(ErrorBody):
    """K-58: iptali engelleyen satışlar; önce onlar iptal edilir."""

    blocking: list[BlockingSale] = Field(default_factory=list)


class VoidTarget(Model):
    id: int
    instrument: str
    trade_date: date
    side: Literal["BUY", "SELL"]
    units: DecimalStr
    unit_price: DecimalStr
    fee: DecimalStr
    external_ref: str | None
    note: str | None


def void_target(preview: VoidPreview) -> VoidTarget:
    stored = preview.stored
    tx = stored.transaction
    return VoidTarget(
        id=stored.id,
        instrument=tx.instrument,
        trade_date=tx.trade_date,
        side=tx.side.value,
        units=tx.units,
        unit_price=tx.unit_price,
        fee=tx.fee,
        external_ref=stored.external_ref,
        note=stored.note,
    )


class VoidPreviewBody(Model):
    profile: ProfileSlug
    target: VoidTarget
    reason: str
    confirmation: dict[str, str]
    changed: bool


class PaydayLine(Model):
    asset_class: str
    class_name: str
    instrument: str
    amount: DecimalStr
    status: PaydayStatus
    price_day: date | None
    price: DecimalStr | None
    units: DecimalStr | None
    spent: DecimalStr | None
    leftover: DecimalStr | None
    reason: str | None


class PaydayPreviewBody(Model):
    """`confirmation` yalnız uygulanabilir alım varsa verilir (K-113)."""

    profile: ProfileSlug
    payday: date
    reapply_voided: bool
    window_end: date
    retry_after: date
    missing_prices: list[str]
    lines: list[PaydayLine]
    ready: int
    confirmation: dict[str, str] | None
    changed: bool


def payday_lines(plan: PaydayPurchasePlan, names: Mapping[str, str]) -> list[PaydayLine]:
    return [
        PaydayLine(
            asset_class=line.asset_class,
            class_name=names.get(line.asset_class, line.asset_class),
            instrument=line.instrument,
            amount=line.amount,
            status=line.status,
            price_day=line.price_day,
            price=line.price,
            units=line.units,
            spent=line.spent,
            leftover=line.leftover,
            reason=line.reason,
        )
        for line in plan.lines
    ]


class RefreshResult(Model):
    """`accepted`: istek bırakıldı, fiyat işini systemd başlatır (K-122, K-123)."""

    accepted: bool
    refresh: RefreshInfo
