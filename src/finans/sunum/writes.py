"""Web'den yazma: form okunur, önizlenir; onayda girdi yeniden okunur, sonuç yeniden hesaplanır
ve önizlemeyle aynıysa nonce ile aynı veritabanı işleminde kaydedilir (K-105, K-116, K-126).
Hesap ve ret kuralları application'dadır; burada web'e özel hesap yoktur."""

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Final, Literal

from finans import bootstrap
from finans.application.inputs import InputError, parse_amount, parse_day
from finans.application.paper import (
    PaperPlan,
    PaydayPurchase,
    PaydayPurchasePlan,
    plan_paper_buy,
    plan_paper_sell,
    plan_payday_purchases,
    record_payday_purchases,
)
from finans.application.previews import TradePreview, VoidPreview, preview_transaction, preview_void
from finans.application.settings import payday_for
from finans.application.transactions import add_transaction, digest, void_transaction
from finans.domain.models import Side, Transaction
from finans.domain.numeric import canonical_text
from finans.domain.schedule import logical_date
from finans.ports.clock import BUSINESS_TZ
from finans.ports.unit_of_work import UnitOfWork
from finans.settings import Settings
from finans.sunum.views import load_config

type TradeKind = Literal["alis", "satis"]
TRADE_KINDS: Final[tuple[TradeKind, ...]] = ("alis", "satis")
REF_MAX: Final = 64
REASON_MAX: Final = 200
_LOG = logging.getLogger("finans.sunum")


class FormErrors(Exception):
    """Alan adı → düzeltme cümlesi; form aynı değerlerle yeniden gösterilir."""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("; ".join(fields.values()))
        self.fields = fields


class ResultChanged(Exception):
    """Önizlemeden sonra veri değişti; kayıt yapılmadı."""


@dataclass(frozen=True, slots=True)
class TradeRequest:
    kind: TradeKind
    code: str
    day: date
    # Gerçek profilde dekonttaki adet ve fiyat; sanalda alım tutarla, satış adetle ya da tümü.
    units: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fee: Decimal = Decimal(0)
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedTrade:
    preview: TradePreview
    paper: PaperPlan | None

    @property
    def result(self) -> str:
        """Onay formunun imzaladığı sonuç; kayıtta farklıysa yeni önizleme gösterilir."""
        p = self.preview
        parts = [
            digest(p.transaction),
            p.ref or "",
            canonical_text(p.units_before),
            canonical_text(p.units_after),
            *(str(issue) for issue in p.warnings),
        ]
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Recorded:
    """`number`: işlem numarası; maaş günü planında kaydedilen alım sayısı."""

    number: int
    duplicate: bool


def _given(value: Decimal | None) -> Decimal:
    if value is None:
        raise TypeError("read_trade bu alanı her zaman doldurur")
    return value


def _field(form: Mapping[str, str], name: str) -> str:
    return form.get(name, "").strip()


def _amount(
    form: Mapping[str, str], name: str, label: str, errors: dict[str, str], *, fee: bool = False
) -> Decimal | None:
    text = _field(form, name) or ("0" if fee else "")
    if not text:
        errors[name] = f"{label} boş bırakılamaz."
        return None
    try:
        value = parse_amount(label, text, decimal=",")
    except InputError as exc:
        errors[name] = str(exc)
        return None
    if not value.is_finite() or value < 0 or (value == 0 and not fee):
        errors[name] = f"{label} negatif olamaz." if fee else f"{label} sıfırdan büyük olmalı."
        return None
    return value


def _checked(errors: dict[str, str], day: date | None) -> date:
    if errors or day is None:
        raise FormErrors(errors)
    return day


def read_trade(kind: TradeKind, form: Mapping[str, str], *, sanal: bool) -> TradeRequest:
    errors: dict[str, str] = {}
    code = _field(form, "fon")
    if not code:
        errors["fon"] = "Fon seç."
    day = None
    try:
        day = parse_day(_field(form, "gun"))
    except InputError as exc:
        errors["gun"] = str(exc)
    if sanal and kind == "alis":
        amount = _amount(form, "tutar", "Tutar", errors)
        fee = _amount(form, "komisyon", "Komisyon", errors, fee=True)
        return TradeRequest(kind, code, _checked(errors, day), amount=amount, fee=_given(fee))
    if sanal:
        units = None if _field(form, "tumu") == "1" else _amount(form, "adet", "Adet", errors)
        return TradeRequest(kind, code, _checked(errors, day), units=units)
    units = _amount(form, "adet", "Adet", errors)
    price = _amount(form, "fiyat", "Birim fiyat", errors)
    fee = _amount(form, "komisyon", "Komisyon", errors, fee=True)
    ref = _field(form, "dekont")
    if len(ref) > REF_MAX:
        errors["dekont"] = f"Dekont no en fazla {REF_MAX} karakter olabilir."
    day = _checked(errors, day)
    return TradeRequest(kind, code, day, units, price, fee=_given(fee), ref=ref or None)


def trade_fields(kind: TradeKind, form: Mapping[str, str], *, sanal: bool) -> dict[str, str]:
    """İmzalanacak girdi, yazıldığı gibi: normalleştirilse fiyatın girilen basamakları (K-64)
    kaybolurdu. Onayda `read_trade` bunu yeniden okur ve doğrular."""
    if sanal and kind == "alis":
        names: tuple[str, ...] = ("fon", "gun", "tutar", "komisyon")
    elif sanal:
        names = ("fon", "gun", "adet", "tumu")
    else:
        names = ("fon", "gun", "adet", "fiyat", "komisyon", "dekont")
    return {name: _field(form, name) for name in names}


def plan_trade(uow: UnitOfWork, request: TradeRequest, *, sanal: bool, today: date) -> PlannedTrade:
    paper = None
    if sanal and request.kind == "alis":
        paper = plan_paper_buy(
            uow, code=request.code, amount=_given(request.amount), day=request.day, fee=request.fee
        )
        tx = paper.transaction
    elif sanal:
        paper = plan_paper_sell(uow, code=request.code, units=request.units, day=request.day)
        tx = paper.transaction
    else:
        side = Side.BUY if request.kind == "alis" else Side.SELL
        units, price = _given(request.units), _given(request.price)
        tx = Transaction(request.code, request.day, side, units, price, request.fee)
    preview = preview_transaction(uow, tx, ref=request.ref, today=today)
    if paper is not None:
        # Sanal fiyat kayıttaki TEFAS fiyatıdır (K-109); K-64'te denetlenecek bir şey yok.
        preview = replace(preview, warnings=())
    return PlannedTrade(preview, paper)


def preview_trade(conf: Settings, request: TradeRequest, *, today: date) -> PlannedTrade:
    with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
        return plan_trade(uow, request, sanal=bootstrap.is_sanal_profile(conf), today=today)


def record_trade(
    conf: Settings, request: TradeRequest, *, nonce: str, expected: str, now: datetime, today: date
) -> Recorded:
    sanal = bootstrap.is_sanal_profile(conf)
    with bootstrap.open_unit_of_work(conf, migrate=False) as uow:
        used = uow.submissions.used(nonce)
        if used is not None:
            return Recorded(int(used), duplicate=True)
        planned = plan_trade(uow, request, sanal=sanal, today=today)
        if planned.result != expected:
            raise ResultChanged
        txn_id = add_transaction(
            uow, planned.preview.transaction, ref=request.ref, note=None, now=now
        )
        uow.submissions.record(nonce, ref=str(txn_id), at=now)
    # K-126: log'a tutar, adet, fiyat ve gerekçe yazılmaz.
    _LOG.info("İşlem kaydedildi: #%d %s (%s)", txn_id, request.kind, conf.profile)
    return Recorded(txn_id, duplicate=False)


def choices(conf: Settings, kind: TradeKind) -> list[tuple[str, str]]:
    """Alışta yalnız etkin fonlar (K-51); satışta pasif fonlar da."""
    with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
        stored = uow.instruments.list(include_inactive=kind == "satis")
    return [
        (s.instrument.code, s.instrument.name or s.instrument.code)
        for s in sorted(stored, key=lambda s: s.instrument.code)
    ]


def read_reason(form: Mapping[str, str]) -> str:
    reason = _field(form, "gerekce")
    if not reason:
        raise FormErrors(
            {"gerekce": "Gerekçe boş bırakılamaz; neden iptal edildiği kayıtta kalır."}
        )
    if len(reason) > REASON_MAX:
        raise FormErrors({"gerekce": f"Gerekçe en fazla {REASON_MAX} karakter olabilir."})
    return reason


def void_preview(conf: Settings, txn_id: int) -> VoidPreview:
    with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
        return preview_void(uow, txn_id)


def void_result(preview: VoidPreview) -> str:
    stored = preview.stored
    return hashlib.sha256(f"{stored.id}\n{digest(stored.transaction)}".encode()).hexdigest()


def record_void(
    conf: Settings, txn_id: int, *, reason: str, nonce: str, expected: str, now: datetime
) -> Recorded:
    with bootstrap.open_unit_of_work(conf, migrate=False) as uow:
        used = uow.submissions.used(nonce)
        if used is not None:
            return Recorded(int(used), duplicate=True)
        if void_result(preview_void(uow, txn_id)) != expected:
            raise ResultChanged
        void_transaction(uow, txn_id, reason=reason, now=now)
        uow.submissions.record(nonce, ref=str(txn_id), at=now)
    _LOG.info("İşlem iptal edildi: #%d (%s)", txn_id, conf.profile)
    return Recorded(txn_id, duplicate=False)


@dataclass(frozen=True, slots=True)
class PaydayRequest:
    payday: date
    reapply_voided: bool


def default_payday(conf: Settings, now: datetime) -> PaydayRequest:
    """Son maaş günü, her ayın kendi ayarındaki maaş gününe göre (K-127)."""
    config = load_config(conf)
    with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
        schedule = payday_for(uow, config)
    day = logical_date("payday", now.astimezone(BUSINESS_TZ), payday=schedule)
    return PaydayRequest(day, reapply_voided=False)


def read_payday(form: Mapping[str, str]) -> PaydayRequest:
    errors: dict[str, str] = {}
    day = None
    try:
        day = parse_day(_field(form, "maas_gunu"))
    except InputError as exc:
        errors["maas_gunu"] = str(exc)
    return PaydayRequest(_checked(errors, day), _field(form, "iptaller") == "1")


def payday_fields(request: PaydayRequest) -> dict[str, str]:
    return {
        "maas_gunu": request.payday.isoformat(),
        "iptaller": "1" if request.reapply_voided else "",
    }


def _plan_payday(
    uow: UnitOfWork, conf: Settings, request: PaydayRequest, today: date
) -> PaydayPurchasePlan:
    return plan_payday_purchases(
        uow,
        load_config(conf),
        payday=request.payday,
        today=today,
        reapply_voided=request.reapply_voided,
    )


def preview_payday(conf: Settings, request: PaydayRequest, *, today: date) -> PaydayPurchasePlan:
    with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
        return _plan_payday(uow, conf, request, today)


def ready(plan: PaydayPurchasePlan) -> list[PaydayPurchase]:
    return [] if plan.missing_prices else [line for line in plan.lines if line.status == "ready"]


def payday_result(plan: PaydayPurchasePlan) -> str:
    def text(value: Decimal | None) -> str:
        return "" if value is None else canonical_text(value)

    parts = [plan.payday.isoformat(), *plan.missing_prices]
    parts += [
        f"{line.ref}|{line.status}|{line.price_day}|{text(line.price)}|{text(line.units)}"
        for line in plan.lines
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def record_payday(
    conf: Settings,
    request: PaydayRequest,
    *,
    nonce: str,
    expected: str,
    now: datetime,
    today: date,
) -> Recorded:
    with bootstrap.open_unit_of_work(conf, migrate=False) as uow:
        used = uow.submissions.used(nonce)
        if used is not None:
            return Recorded(int(used), duplicate=True)
        plan = _plan_payday(uow, conf, request, today)
        if payday_result(plan) != expected or not ready(plan):
            raise ResultChanged
        trades = record_payday_purchases(uow, plan, now=now)
        uow.submissions.record(nonce, ref=str(len(trades)), at=now)
    _LOG.info("Maaş günü planı uygulandı: %d alım (%s)", len(trades), conf.profile)
    return Recorded(len(trades), duplicate=False)
