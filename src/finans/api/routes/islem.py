"""Yazma uçları (K-105, K-137, K-138): önizleme → onay.

Önizleme girdiyi ve sonucu Access e-postasına bağlı, 10 dakika geçerli bir HMAC ile imzalar. Kayıt
girdiyi yeniden okur, sonucu yeniden hesaplar ve yalnız önizlemeyle aynıysa nonce ile aynı
veritabanı işleminde yazar; farklıysa 409 ve yeni önizleme döner. Aynı onay ikinci kez gelirse
yazılmaz, ilk kaydın numarası `duplicate` ile döner."""

import logging
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path
from starlette.responses import Response

from finans.api.context import ApiContext, context, viewer
from finans.api.encoding import CanonicalJSONResponse, error_response
from finans.api.errors import HTTP_MESSAGES, INVALID, page_errors
from finans.api.models import PAGE_RESPONSES
from finans.api.pages import class_names, refresh_info
from finans.api.writing import (
    ConfirmInput,
    PaydayInput,
    PaydayPreviewBody,
    ReasonInput,
    RefreshResult,
    Saved,
    TradeError,
    TradeInput,
    TradePreviewBody,
    VoidBlocked,
    VoidPreviewBody,
    VoidTarget,
    blocking_sale,
    json_fields,
    payday_lines,
    trade_preview_body,
    void_target,
)
from finans.application.paper import NoPriceError
from finans.application.previews import VoidPreview
from finans.application.transactions import VoidBlockedError
from finans.domain.models import DomainError
from finans.ports.clock import Clock
from finans.settings import Settings
from finans.sunum.confirm import Verified, sign, verify
from finans.sunum.profiles import BY_SLUG, ProfileSlug
from finans.sunum.views import ask_for_refresh, load_config
from finans.sunum.writes import (
    TRADE_KINDS,
    FormErrors,
    PaydayRequest,
    ResultChanged,
    TradeKind,
    TradeRequest,
    choices,
    default_payday,
    payday_fields,
    payday_result,
    preview_payday,
    preview_trade,
    read_payday,
    read_reason,
    read_trade,
    ready,
    record_payday,
    record_trade,
    record_void,
    trade_fields,
    void_preview,
    void_result,
)

REFUSED: Final = "İstek reddedildi."
EXPIRED: Final = (
    "Önizleme 10 dakikadan eski; onay süresi doldu, hiçbir şey kaydedilmedi. Yeniden önizle."
)
REFRESH_UNWRITABLE: Final = "Güncelleme isteği yazılamadı; Sistem sayfasına bakın."
_LOG = logging.getLogger("finans.api")

router = APIRouter(prefix="/api/{profil}", tags=["yazma"], responses=PAGE_RESPONSES)


@dataclass(frozen=True, slots=True)
class Writer:
    conf: Settings
    slug: ProfileSlug
    clock: Clock
    # Onay jetonu oturuma değil Access e-postasına bağlıdır (K-137).
    session: str
    key: bytes

    @property
    def sanal(self) -> bool:
        return self.conf.profile == "sanal"

    def sign(self, fields: dict[str, str]) -> dict[str, str]:
        return sign(self.key, self.session, {"profil": self.slug, **fields}, now=self.clock.now())


def writer(
    profil: Annotated[ProfileSlug, Path(description="Profil (K-125)")],
    ctx: Annotated[ApiContext, Depends(context)],
    email: Annotated[str, Depends(viewer)],
) -> Writer:
    key = ctx.api.confirm_key.get_secret_value().encode()
    return Writer(ctx.profiles[BY_SLUG[profil]], profil, ctx.clock, email.casefold(), key)


W = Annotated[Writer, Depends(writer)]


def _invalid(fields: dict[str, str]) -> Response:
    return error_response(422, INVALID, json_fields(fields))


def _refused(w: Writer, reason: str) -> Response:
    _LOG.warning("Onay reddedildi (%s): %s", w.slug, reason)
    return error_response(403, REFUSED)


def _confirmed(w: Writer, body: ConfirmInput, kind: str) -> Verified | Response:
    verified = verify(w.key, w.session, body.confirmation, now=w.clock.now())
    if verified.status == "expired":
        return error_response(422, EXPIRED)
    if verified.status != "ok":
        return _refused(w, "imza geçersiz")
    if verified.fields.get("profil") != w.slug:
        return _refused(w, "başka profilin onayı")
    if verified.fields.get("islem") != kind:
        return _refused(w, "başka bir işlemin onayı")
    return verified


def _saved(number: int, duplicate: bool) -> Response:
    return CanonicalJSONResponse(Saved(number=number, duplicate=duplicate))


def _trade_kind(value: str | None) -> TradeKind | None:
    return next((kind for kind in TRADE_KINDS if kind == value), None)


def _trade_preview(
    w: Writer, kind: TradeKind, form: dict[str, str], request: TradeRequest, *, changed: bool
) -> Response:
    try:
        planned = preview_trade(w.conf, request, today=w.clock.today())
    except NoPriceError as exc:
        days = [day for day in (exc.before, exc.after) if day is not None]
        problem = TradeError(error=str(exc), fields={"day": str(exc)}, price_days=days)
        return CanonicalJSONResponse(problem, status_code=422)
    except DomainError as exc:
        return error_response(422, str(exc))
    fields = {"islem": kind, **trade_fields(kind, form, sanal=w.sanal), "sonuc": planned.result}
    names = dict(choices(w.conf, "satis"))
    body = trade_preview_body(w.slug, kind, planned, names, w.sign(fields), changed=changed)
    return CanonicalJSONResponse(body, status_code=409 if changed else 200)


TRADE_ERRORS: Final[dict[int | str, dict[str, object]]] = {
    422: {"model": TradeError, "description": "Girdi geçersiz ya da işlem yapılamaz"},
}


@router.post("/islemler/{tur}/onizle", response_model=TradePreviewBody, responses=TRADE_ERRORS)
def trade_preview(w: W, tur: TradeKind, body: TradeInput) -> Response:
    form = body.form()
    try:
        request = read_trade(tur, form, sanal=w.sanal)
    except FormErrors as exc:
        return _invalid(exc.fields)
    with page_errors():
        return _trade_preview(w, tur, form, request, changed=False)


@router.post(
    "/islemler/kaydet",
    response_model=Saved,
    responses={
        **TRADE_ERRORS,
        409: {"model": TradePreviewBody, "description": "Sonuç değişti; yeni önizleme"},
    },
)
def trade_save(w: W, body: ConfirmInput) -> Response:
    kind = _trade_kind(body.confirmation.get("islem"))
    if kind is None:
        return _refused(w, "işlem türü yok")
    verified = _confirmed(w, body, kind)
    if isinstance(verified, Response):
        return verified
    fields = verified.fields
    try:
        request = read_trade(kind, fields, sanal=w.sanal)
    except FormErrors as exc:
        return _invalid(exc.fields)
    with page_errors():
        try:
            recorded = record_trade(
                w.conf,
                request,
                nonce=verified.nonce,
                expected=fields.get("sonuc", ""),
                now=w.clock.now(),
                today=w.clock.today(),
            )
        except ResultChanged:
            return _trade_preview(w, kind, fields, request, changed=True)
        except DomainError as exc:
            return error_response(422, str(exc))
    return _saved(recorded.number, recorded.duplicate)


VOID_ERRORS: Final[dict[int | str, dict[str, object]]] = {
    422: {"model": VoidBlocked, "description": "Girdi geçersiz ya da iptali satışlar engelliyor"},
}


def _void_target(w: Writer, number: int) -> VoidPreview | Response:
    try:
        return void_preview(w.conf, number)
    except VoidBlockedError as exc:
        blocked = VoidBlocked(error=str(exc), blocking=[blocking_sale(s) for s in exc.blocking])
        return CanonicalJSONResponse(blocked, status_code=422)
    except DomainError as exc:
        return error_response(404, str(exc))


def _void_preview(w: Writer, number: int, reason: str, *, changed: bool) -> Response:
    target = _void_target(w, number)
    if isinstance(target, Response):
        return target
    fields = {"islem": "iptal", "no": str(number), "gerekce": reason, "sonuc": void_result(target)}
    body = VoidPreviewBody(
        profile=w.slug,
        target=void_target(target),
        reason=reason,
        confirmation=w.sign(fields),
        changed=changed,
    )
    return CanonicalJSONResponse(body, status_code=409 if changed else 200)


@router.get("/islemler/{no}/iptal", response_model=VoidTarget, responses=VOID_ERRORS)
def void_info(w: W, no: int) -> Response:
    with page_errors():
        target = _void_target(w, no)
    if isinstance(target, Response):
        return target
    return CanonicalJSONResponse(void_target(target))


@router.post("/islemler/{no}/iptal/onizle", response_model=VoidPreviewBody, responses=VOID_ERRORS)
def void_preview_endpoint(w: W, no: int, body: ReasonInput) -> Response:
    try:
        reason = read_reason({"gerekce": body.reason})
    except FormErrors as exc:
        return _invalid(exc.fields)
    with page_errors():
        return _void_preview(w, no, reason, changed=False)


@router.post(
    "/islemler/{no}/iptal/kaydet",
    response_model=Saved,
    responses={
        **VOID_ERRORS,
        409: {"model": VoidPreviewBody, "description": "Sonuç değişti; yeni önizleme"},
    },
)
def void_save(w: W, no: int, body: ConfirmInput) -> Response:
    verified = _confirmed(w, body, "iptal")
    if isinstance(verified, Response):
        return verified
    fields = verified.fields
    if fields.get("no") != str(no):
        return _refused(w, "başka bir işlemin iptali")
    try:
        reason = read_reason(fields)
    except FormErrors:
        return _refused(w, "imzalı gerekçe geçersiz")
    with page_errors():
        try:
            recorded = record_void(
                w.conf,
                no,
                reason=reason,
                nonce=verified.nonce,
                expected=fields.get("sonuc", ""),
                now=w.clock.now(),
            )
        except ResultChanged:
            return _void_preview(w, no, reason, changed=True)
        except VoidBlockedError as exc:
            blocked = VoidBlocked(error=str(exc), blocking=[blocking_sale(s) for s in exc.blocking])
            return CanonicalJSONResponse(blocked, status_code=422)
        except DomainError as exc:
            return error_response(422, str(exc))
    return _saved(recorded.number, recorded.duplicate)


def _sanal_only(w: Writer) -> Response | None:
    """K-113: maaş günü planını uygulamak yalnız sanal profilde; gerçek profilde adres yoktur."""
    return None if w.sanal else error_response(404, HTTP_MESSAGES[404])


def _payday_preview(w: Writer, request: PaydayRequest, *, changed: bool) -> Response:
    plan = preview_payday(w.conf, request, today=w.clock.today())
    applicable = ready(plan)
    confirmation = None
    if applicable:
        fields = {"islem": "maas-gunu", **payday_fields(request), "sonuc": payday_result(plan)}
        confirmation = w.sign(fields)
    body = PaydayPreviewBody(
        profile=w.slug,
        payday=plan.payday,
        reapply_voided=request.reapply_voided,
        window_end=plan.window_end,
        retry_after=plan.retry_after,
        missing_prices=list(plan.missing_prices),
        lines=payday_lines(plan, class_names(load_config(w.conf))),
        ready=len(applicable),
        confirmation=confirmation,
        changed=changed,
    )
    return CanonicalJSONResponse(body, status_code=409 if changed else 200)


@router.get("/maas-gunu", response_model=PaydayPreviewBody)
def payday_default(w: W) -> Response:
    """Son maaş gününün planı; her ay kendi ayarındaki maaş gününe göre (K-127)."""
    if (missing := _sanal_only(w)) is not None:
        return missing
    with page_errors():
        return _payday_preview(w, default_payday(w.conf, w.clock.now()), changed=False)


@router.post("/maas-gunu/onizle", response_model=PaydayPreviewBody)
def payday_preview_endpoint(w: W, body: PaydayInput) -> Response:
    if (missing := _sanal_only(w)) is not None:
        return missing
    try:
        request = read_payday(body.form())
    except FormErrors as exc:
        return _invalid(exc.fields)
    with page_errors():
        return _payday_preview(w, request, changed=False)


@router.post(
    "/maas-gunu/kaydet",
    response_model=Saved,
    responses={409: {"model": PaydayPreviewBody, "description": "Sonuç değişti; yeni önizleme"}},
)
def payday_save(w: W, body: ConfirmInput) -> Response:
    if (missing := _sanal_only(w)) is not None:
        return missing
    verified = _confirmed(w, body, "maas-gunu")
    if isinstance(verified, Response):
        return verified
    try:
        request = read_payday(verified.fields)
    except FormErrors:
        return _refused(w, "imzalı maaş günü geçersiz")
    with page_errors():
        try:
            recorded = record_payday(
                w.conf,
                request,
                nonce=verified.nonce,
                expected=verified.fields.get("sonuc", ""),
                now=w.clock.now(),
                today=w.clock.today(),
            )
        except ResultChanged:
            return _payday_preview(w, request, changed=True)
    return _saved(recorded.number, recorded.duplicate)


@router.post("/fiyat-guncelle", response_model=RefreshResult)
def refresh(w: W) -> Response:
    """Fiyat çekilmez; istek dosyası bırakılır, işi systemd başlatır (K-122, K-123)."""
    with page_errors():
        try:
            status = ask_for_refresh(w.conf, w.clock)
        except OSError:
            return error_response(503, REFRESH_UNWRITABLE)
    result = RefreshResult(accepted=status.decision.allowed, refresh=refresh_info(status))
    return CanonicalJSONResponse(result)
