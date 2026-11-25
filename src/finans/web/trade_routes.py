"""Yazma uçları: işlem girişi ve iptal; form → önizleme → imzalı onay → kayıt
(K-105, K-116, K-125, K-126). Her uç önce formu ve kilidi denetler."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Final, Protocol

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from finans.application.transactions import VoidBlockedError
from finans.domain.models import DomainError
from finans.ports.clock import Clock
from finans.settings import Profile, Settings
from finans.web.confirm import sign, verify
from finans.web.forms import REFUSED, read_form
from finans.web.lock import WriteLock
from finans.web.views import PAGE_ERRORS, PageError
from finans.web.writes import (
    TRADE_KINDS,
    FormErrors,
    Recorded,
    ResultChanged,
    TradeKind,
    choices,
    preview_trade,
    read_reason,
    read_trade,
    record_trade,
    record_void,
    trade_fields,
    void_preview,
    void_result,
)

HEADINGS: Final[dict[tuple[Profile, TradeKind], tuple[str, str]]] = {
    ("real", "alis"): ("Alım ekle", "Dekonttaki adet ve fiyatla."),
    ("real", "satis"): ("Satış ekle", "Dekonttaki adet ve fiyatla."),
    ("sanal", "alis"): (
        "Sanal alım",
        "Tutarla; adet o günün kayıtlı fiyatından hesaplanır, artan tutar fona girmez.",
    ),
    ("sanal", "satis"): (
        "Sanal satış",
        "Adetle ya da eldeki payın tümü; fiyat o günün kayıtlı fiyatıdır.",
    ),
}
CONFIRM_LABELS: Final[dict[tuple[Profile, TradeKind], str]] = {
    ("real", "alis"): "Gerçek alımı kaydet",
    ("real", "satis"): "Gerçek satışı kaydet",
    ("sanal", "alis"): "Sanal alımı kaydet",
    ("sanal", "satis"): "Sanal satışı kaydet",
}
EXPIRED: Final = (
    "Önizleme 10 dakikadan eski; onay süresi doldu, hiçbir şey kaydedilmedi. Formu yeniden önizle."
)


class Page(Protocol):
    def __call__(
        self, request: Request, name: str, context: dict[str, object], *, status: int = 200
    ) -> Response: ...


class LockPage(Protocol):
    def __call__(self, request: Request, back: str, *, status: int = 200) -> Response: ...


@dataclass(frozen=True, slots=True)
class WriteContext:
    profile: Profile
    prefix: str
    conf: Settings
    key: bytes
    origin: str
    lock: WriteLock
    time: Clock
    page: Page
    lock_page: LockPage


type Handler = Callable[[Request], Coroutine[Any, Any, Response]]


def write_routes(w: WriteContext) -> list[BaseRoute]:
    sanal = w.profile == "sanal"
    prefix = w.prefix

    def gate(request: Request, back: str) -> Response | None:
        state = w.lock.state(request.state.session)
        if state.status == "disabled":
            return w.lock_page(request, back, status=403)
        if state.status == "locked":
            return RedirectResponse(f"{prefix}/kilit?sonra={back}", status_code=303)
        return None

    def failure(request: Request, message: str, status: int) -> Response:
        return w.page(request, "hata.html", {"message": message}, status=status)

    def posted(body: Callable[[Request, dict[str, str]], Response]) -> Handler:
        async def handler(request: Request) -> Response:
            form = await read_form(request, origin=w.origin, key=w.key)
            if isinstance(form, Response):
                return form
            try:
                return await run_in_threadpool(body, request, form)
            except (PageError, *PAGE_ERRORS) as exc:
                return failure(request, str(exc), 503)

        return handler

    def form_page(
        request: Request,
        kind: TradeKind,
        values: dict[str, str],
        *,
        errors: dict[str, str] | None = None,
        problem: str | None = None,
        status: int = 200,
    ) -> Response:
        heading, lead = HEADINGS[(w.profile, kind)]
        context: dict[str, object] = {
            "kind": kind,
            "heading": heading,
            "lead": lead,
            "values": values,
            "errors": errors or {},
            "problem": problem,
            "choices": choices(w.conf, kind),
        }
        return w.page(request, "islem_form.html", context, status=status)

    def preview_page(
        request: Request, kind: TradeKind, form: dict[str, str], *, changed: bool = False
    ) -> Response:
        """`changed`: onayda sonuç farklı çıktı; yeni önizleme 409 ile gösterilir."""
        trade = read_trade(kind, form, sanal=sanal)
        try:
            planned = preview_trade(w.conf, trade, today=w.time.today())
        except DomainError as exc:
            status = 409 if changed else 400
            return form_page(request, kind, form, problem=str(exc), status=status)
        entered = trade_fields(kind, form, sanal=sanal)
        fields = {"profil": w.profile, "islem": kind, **entered, "sonuc": planned.result}
        context: dict[str, object] = {
            "kind": kind,
            "planned": planned,
            "names": dict(choices(w.conf, "satis")),
            "signed": sign(w.key, request.state.session, fields, now=w.time.now()),
            "edit": entered,
            "confirm_label": CONFIRM_LABELS[(w.profile, kind)],
            "changed": changed,
        }
        return w.page(request, "islem_onizle.html", context, status=409 if changed else 200)

    def new_trade(kind: TradeKind) -> Callable[[Request], Response]:
        def handler(request: Request) -> Response:
            if (denied := gate(request, f"{prefix}/islemler/yeni/{kind}")) is not None:
                return denied
            try:
                return form_page(request, kind, {"gun": w.time.today().isoformat()})
            except (PageError, *PAGE_ERRORS) as exc:
                return failure(request, str(exc), 503)

        return handler

    def previewing(kind: TradeKind) -> Callable[[Request, dict[str, str]], Response]:
        def body(request: Request, form: dict[str, str]) -> Response:
            if (denied := gate(request, f"{prefix}/islemler/yeni/{kind}")) is not None:
                return denied
            if form.get("duzenle") == "1":
                return form_page(request, kind, form)
            try:
                read_trade(kind, form, sanal=sanal)
            except FormErrors as exc:
                return form_page(request, kind, form, errors=exc.fields, status=400)
            return preview_page(request, kind, form)

        return body

    def duplicate(request: Request, kind: str, recorded: Recorded) -> Response:
        if kind == "iptal":
            message = f"Bu onay zaten kullanıldı; #{recorded.txn_id} numaralı işlem iptal edildi."
        else:
            message = f"Bu onay zaten kullanıldı; işlem #{recorded.txn_id} olarak kaydedildi."
        return failure(request, message, 409)

    def saving_trade(
        request: Request, kind: TradeKind, fields: dict[str, str], nonce: str
    ) -> Response:
        try:
            trade = read_trade(kind, fields, sanal=sanal)
            recorded = record_trade(
                w.conf,
                trade,
                nonce=nonce,
                expected=fields.get("sonuc", ""),
                now=w.time.now(),
                today=w.time.today(),
            )
        except FormErrors as exc:
            return form_page(request, kind, fields, errors=exc.fields, status=400)
        except ResultChanged:
            return preview_page(request, kind, fields, changed=True)
        except DomainError as exc:
            return form_page(request, kind, fields, problem=str(exc), status=409)
        if recorded.duplicate:
            return duplicate(request, kind, recorded)
        target = f"{prefix}/islemler?islem={kind}&no={recorded.txn_id}"
        return RedirectResponse(target, status_code=303)

    def void_page(
        request: Request,
        txn_id: int,
        *,
        reason: str = "",
        errors: dict[str, str] | None = None,
        confirm: bool = False,
        changed: bool = False,
        status: int = 200,
    ) -> Response:
        """`confirm`: gerekçe geçerli; imzalı onay formuyla önizleme gösterilir."""
        try:
            preview = void_preview(w.conf, txn_id)
        except VoidBlockedError as exc:
            context: dict[str, object] = {"mode": "blocked", "no": txn_id, "blocking": exc.blocking}
            return w.page(request, "iptal.html", context, status=409)
        except DomainError as exc:
            return failure(request, str(exc), 404)
        signed = None
        if confirm:
            fields = {
                "profil": w.profile,
                "islem": "iptal",
                "no": str(txn_id),
                "gerekce": reason,
                "sonuc": void_result(preview),
            }
            signed = sign(w.key, request.state.session, fields, now=w.time.now())
        context = {
            "mode": "onizle" if confirm else "form",
            "no": txn_id,
            "stored": preview.stored,
            "reason": reason,
            "errors": errors or {},
            "signed": signed,
            "changed": changed,
        }
        return w.page(request, "iptal.html", context, status=status)

    def void_form(request: Request) -> Response:
        txn_id: int = request.path_params["no"]
        if (denied := gate(request, f"{prefix}/islemler/{txn_id}/iptal")) is not None:
            return denied
        try:
            return void_page(request, txn_id)
        except (PageError, *PAGE_ERRORS) as exc:
            return failure(request, str(exc), 503)

    def voiding(request: Request, form: dict[str, str]) -> Response:
        txn_id: int = request.path_params["no"]
        if (denied := gate(request, f"{prefix}/islemler/{txn_id}/iptal")) is not None:
            return denied
        reason = form.get("gerekce", "")
        if form.get("duzenle") == "1":
            return void_page(request, txn_id, reason=reason)
        try:
            reason = read_reason(form)
        except FormErrors as exc:
            return void_page(request, txn_id, reason=reason, errors=exc.fields, status=400)
        return void_page(request, txn_id, reason=reason, confirm=True)

    def saving_void(request: Request, fields: dict[str, str], nonce: str) -> Response:
        number = fields.get("no", "")
        if not (number.isascii() and number.isdigit()):
            return PlainTextResponse(REFUSED, status_code=403)
        txn_id = int(number)
        try:
            reason = read_reason(fields)
            recorded = record_void(
                w.conf,
                txn_id,
                reason=reason,
                nonce=nonce,
                expected=fields.get("sonuc", ""),
                now=w.time.now(),
            )
        except FormErrors:
            return PlainTextResponse(REFUSED, status_code=403)
        except ResultChanged:
            reason = fields.get("gerekce", "")
            return void_page(request, txn_id, reason=reason, confirm=True, changed=True, status=409)
        except VoidBlockedError:
            return void_page(request, txn_id)
        except DomainError as exc:
            return failure(request, str(exc), 409)
        if recorded.duplicate:
            return duplicate(request, "iptal", recorded)
        target = f"{prefix}/islemler?islem=iptal&no={txn_id}"
        return RedirectResponse(target, status_code=303)

    def saving(request: Request, form: dict[str, str]) -> Response:
        if (denied := gate(request, f"{prefix}/islemler")) is not None:
            return denied
        verified = verify(w.key, request.state.session, form, now=w.time.now())
        if verified.status == "expired":
            return failure(request, EXPIRED, 400)
        fields = verified.fields
        if verified.status != "ok" or fields.get("profil") != w.profile:
            return PlainTextResponse(REFUSED, status_code=403)
        kind = fields.get("islem")
        if kind == "iptal":
            return saving_void(request, fields, verified.nonce)
        for trade_kind in TRADE_KINDS:
            if kind == trade_kind:
                return saving_trade(request, trade_kind, fields, verified.nonce)
        return PlainTextResponse(REFUSED, status_code=403)

    routes: list[BaseRoute] = []
    for kind in TRADE_KINDS:
        path = f"{prefix}/islemler/yeni/{kind}"
        routes.append(Route(path, new_trade(kind), methods=["GET"]))
        routes.append(Route(path, posted(previewing(kind)), methods=["POST"]))
    return [
        *routes,
        Route(f"{prefix}/islemler/kaydet", posted(saving), methods=["POST"]),
        Route(f"{prefix}/islemler/{{no:int}}/iptal", void_form, methods=["GET"]),
        Route(f"{prefix}/islemler/{{no:int}}/iptal", posted(voiding), methods=["POST"]),
    ]
