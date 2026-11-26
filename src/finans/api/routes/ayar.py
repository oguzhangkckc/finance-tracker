"""Ayar yazmaları (K-127, K-137): yürürlük tarihli yeni sürüm ve planlanmış sürümden vazgeçme.

Gerçek profilde aynı değişiklik isteğe bağlı olarak sanal portföye de yazılır: önce gerçek, sonra
sanal, ayrı işlemlerle ve her birinde onayın nonce'u kaydedilerek. Sanal yazılamazsa gerçek geri
alınmaz; aynı onay yeniden gönderilince gerçek tekrar yazılmaz, sanal yeniden denenir."""

from typing import Final

from fastapi import APIRouter
from starlette.responses import Response

from finans.api.encoding import CanonicalJSONResponse, error_response
from finans.api.errors import page_errors
from finans.api.models import PAGE_RESPONSES
from finans.api.pages import SettingItem, setting_item
from finans.api.setting_writing import (
    CancelPreviewBody,
    SettingInput,
    SettingPreviewBody,
    SettingSaved,
    profile_proposal,
    profile_result,
    setting_json_fields,
)
from finans.api.writer import W, Writer, confirmed, invalid, refused, saved
from finans.api.writing import ConfirmInput, ReasonInput, Saved
from finans.application.settings import HistoryRow
from finans.domain.models import DomainError
from finans.ports.unit_of_work import StorageBusyError
from finans.settings import Settings
from finans.sunum.setting_writes import (
    ProfileOutcome,
    SettingRequest,
    SettingsView,
    cancel_result,
    cancel_target,
    plan_settings,
    proposal_result,
    read_request_fields,
    read_setting_form,
    record_cancel,
    record_settings,
    request_fields,
    settings_view,
)
from finans.sunum.setting_writes import read_reason as read_cancel_reason
from finans.sunum.views import PAGE_ERRORS, PageError
from finans.sunum.writes import FormErrors, ResultChanged

router = APIRouter(prefix="/api/{profil}", tags=["ayar"], responses=PAGE_RESPONSES)
CHANGED: Final[dict[int | str, dict[str, object]]] = {
    409: {"model": SettingPreviewBody, "description": "Sonuç değişti; yeni önizleme"},
}


def _view(w: Writer) -> SettingsView:
    return settings_view(w.conf, w.clock.today())


def _preview(
    w: Writer, view: SettingsView, setting: SettingRequest, *, carry: bool, changed: bool
) -> Response:
    today = w.clock.today()
    plans = [plan_settings(w.conf, setting, today=today)]
    if setting.also_sanal and w.other is not None:
        plans.append(plan_settings(w.other, setting, today=today))
    if plans[0].problem is not None:
        return error_response(422, plans[0].problem)
    carry_option = any(plan.proposal is not None and plan.proposal.later for plan in plans)
    carry = carry and carry_option
    confirmation = None
    proposals = [plan.proposal for plan in plans if plan.ready and plan.proposal is not None]
    if len(proposals) == len(plans):
        fields = {
            "islem": "ayar",
            **request_fields(setting, view.classes),
            "tasima": "1" if carry else "",
            **dict(zip(("sonuc", "sonuc_sanal"), map(proposal_result, proposals), strict=False)),
        }
        confirmation = w.sign(fields)
    body = SettingPreviewBody(
        day=setting.day,
        plans=[profile_proposal(plan, view) for plan in plans],
        carry_option=carry_option,
        carry=carry,
        confirmation=confirmation,
        changed=changed,
    )
    return CanonicalJSONResponse(body, status_code=409 if changed else 200)


@router.post("/ayarlar/onizle", response_model=SettingPreviewBody)
def setting_preview(w: W, body: SettingInput) -> Response:
    with page_errors():
        view = _view(w)
        if unknown := body.unknown_classes(view.classes):
            return invalid(unknown)
        try:
            setting = read_setting_form(
                body.form(view, w.clock.today()),
                view.classes,
                view.labels,
                sanal_option=w.other is not None,
            )
        except FormErrors as exc:
            return invalid(setting_json_fields(exc.fields))
        return _preview(w, view, setting, carry=body.carry, changed=False)


def _sanal_outcome(
    w: Writer,
    sanal: Settings,
    setting: SettingRequest,
    fields: dict[str, str],
    nonce: str,
    carry: bool,
) -> ProfileOutcome:
    """Gerçek yazıldıktan sonra sanal ayrı işlemde; hatası gerçeği geri almaz."""
    try:
        return record_settings(
            sanal,
            setting,
            nonce=nonce,
            expected=fields.get("sonuc_sanal", ""),
            carry=carry,
            now=w.clock.now(),
            today=w.clock.today(),
        )
    except ResultChanged:
        return ProfileOutcome("sanal", "changed")
    except StorageBusyError:
        return ProfileOutcome("sanal", "busy")
    except (PageError, *PAGE_ERRORS) as exc:
        return ProfileOutcome("sanal", "failed", message=str(exc))


@router.post("/ayarlar/kaydet", response_model=SettingSaved, responses=CHANGED)
def setting_save(w: W, body: ConfirmInput) -> Response:
    verified = confirmed(w, body, "ayar")
    if isinstance(verified, Response):
        return verified
    fields = verified.fields
    with page_errors():
        view = _view(w)
        try:
            setting = read_request_fields(fields, view.classes, view.labels)
        except FormErrors:
            return refused(w, "imzalı ayar alanları geçersiz")
        if setting.also_sanal and w.other is None:
            return refused(w, "sanal profilde sanala da uygula")
        carry = fields.get("tasima") == "1"
        try:
            outcome = record_settings(
                w.conf,
                setting,
                nonce=verified.nonce,
                expected=fields.get("sonuc", ""),
                carry=carry,
                now=w.clock.now(),
                today=w.clock.today(),
            )
        except ResultChanged:
            return _preview(w, view, setting, carry=carry, changed=True)
        except DomainError as exc:
            return error_response(422, str(exc))
        outcomes = [outcome]
        if setting.also_sanal and w.other is not None:
            outcomes.append(_sanal_outcome(w, w.other, setting, fields, verified.nonce, carry))
    return CanonicalJSONResponse(SettingSaved(outcomes=[profile_result(o) for o in outcomes]))


def _cancel_target(w: Writer, number: int) -> HistoryRow | Response:
    """Yalnız henüz yürürlüğe girmemiş sürümden vazgeçilir (K-127)."""
    try:
        return cancel_target(w.conf, number, today=w.clock.today())
    except DomainError as exc:
        return error_response(422, str(exc))


def _cancel_preview(w: Writer, number: int, reason: str, *, changed: bool) -> Response:
    target = _cancel_target(w, number)
    if isinstance(target, Response):
        return target
    fields = {
        "islem": "vazgec",
        "no": str(number),
        "gerekce": reason,
        "sonuc": cancel_result(target.stored),
    }
    body = CancelPreviewBody(
        profile=w.slug,
        target=setting_item(target, _view(w)),
        reason=reason,
        confirmation=w.sign(fields),
        changed=changed,
    )
    return CanonicalJSONResponse(body, status_code=409 if changed else 200)


@router.get("/ayarlar/{no}/vazgec", response_model=SettingItem)
def cancel_info(w: W, no: int) -> Response:
    with page_errors():
        target = _cancel_target(w, no)
        if isinstance(target, Response):
            return target
        return CanonicalJSONResponse(setting_item(target, _view(w)))


@router.post("/ayarlar/{no}/vazgec/onizle", response_model=CancelPreviewBody)
def cancel_preview(w: W, no: int, body: ReasonInput) -> Response:
    try:
        reason = read_cancel_reason({"gerekce": body.reason})
    except FormErrors as exc:
        return invalid(setting_json_fields(exc.fields))
    with page_errors():
        return _cancel_preview(w, no, reason, changed=False)


@router.post(
    "/ayarlar/{no}/vazgec/kaydet",
    response_model=Saved,
    responses={409: {"model": CancelPreviewBody, "description": "Sonuç değişti; yeni önizleme"}},
)
def cancel_save(w: W, no: int, body: ConfirmInput) -> Response:
    verified = confirmed(w, body, "vazgec")
    if isinstance(verified, Response):
        return verified
    fields = verified.fields
    if fields.get("no") != str(no):
        return refused(w, "başka bir sürümün vazgeçmesi")
    try:
        reason = read_cancel_reason(fields)
    except FormErrors:
        return refused(w, "imzalı gerekçe geçersiz")
    with page_errors():
        try:
            recorded = record_cancel(
                w.conf,
                no,
                reason=reason,
                nonce=verified.nonce,
                expected=fields.get("sonuc", ""),
                now=w.clock.now(),
                today=w.clock.today(),
            )
        except ResultChanged:
            return _cancel_preview(w, no, reason, changed=True)
        except DomainError as exc:
            return error_response(422, str(exc))
    return saved(recorded.number, recorded.duplicate)
