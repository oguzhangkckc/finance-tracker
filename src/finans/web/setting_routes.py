"""Ayarlar sayfası ve ayar yazma uçları (K-127): yeni sürüm ve vazgeçme; form → önizleme →
imzalı onay → kayıt, işlemlerle aynı kilit ve onay kuralları (K-126)."""

from functools import partial
from typing import Final

from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from finans.application.settings import STATE_LABELS
from finans.domain.models import DomainError
from finans.ports.unit_of_work import StorageBusyError
from finans.settings import Settings
from finans.web.confirm import sign, verify
from finans.web.forms import REFUSED
from finans.web.setting_writes import (
    TARGET,
    ProfileOutcome,
    SettingRequest,
    SettingsView,
    cancel_result,
    cancel_target,
    change_lines,
    form_total,
    form_values,
    kept_text,
    percent_text,
    plan_settings,
    proposal_result,
    read_reason,
    read_request_fields,
    read_setting_form,
    record_cancel,
    record_settings,
    request_fields,
    settings_view,
)
from finans.web.table import table
from finans.web.tables import PAGE_PARAMS, SETTING_SOURCES, SETTINGS
from finans.web.trade_routes import EXPIRED, WriteContext, write_failure, write_gate, write_posted
from finans.web.views import PAGE_ERRORS, PageError
from finans.web.writes import FormErrors, ResultChanged

# Yeni sürüm formu sınıf başına iki alan taşır; işlem formlarının sınırı yetmez.
MAX_FIELDS: Final = 64
PROFILE_NAMES: Final = {"real": "Gerçek", "sanal": "Sanal"}


def setting_routes(w: WriteContext, *, sanal: Settings | None) -> list[BaseRoute]:
    """`sanal`: gerçek profilde "Sanal portföye de uygula" için sanal profilin ayarları."""
    prefix = w.prefix
    other = sanal if w.profile == "real" else None
    gate = partial(write_gate, w)
    failure = partial(write_failure, w)
    posted = partial(write_posted, w, back=f"{prefix}/ayarlar", max_fields=MAX_FIELDS)

    def view() -> SettingsView:
        return settings_view(w.conf, w.time.today())

    def helpers(settings: SettingsView) -> dict[str, object]:
        return {
            "settings": settings,
            "describe": lambda previous, version, fields: change_lines(
                previous, version, fields, settings
            ),
            "kept": lambda stored, fields: kept_text(stored, fields, settings),
            "states": STATE_LABELS,
            "sources": SETTING_SOURCES,
            "names": PROFILE_NAMES,
            "pct": percent_text,
        }

    def settings_page(request: Request) -> Response:
        try:
            settings = view()
        except (PageError, *PAGE_ERRORS) as exc:
            return failure(request, str(exc), 503)
        rows = table(settings.history, request.query_params, SETTINGS, passthrough=PAGE_PARAMS)
        return w.page(request, "ayarlar.html", {**helpers(settings), "table": rows})

    def form_page(
        request: Request,
        values: dict[str, str],
        *,
        errors: dict[str, str] | None = None,
        problem: str | None = None,
        status: int = 200,
    ) -> Response:
        settings = view()
        total, gap = form_total(values, settings.classes)
        context: dict[str, object] = {
            **helpers(settings),
            "values": values,
            "errors": errors or {},
            "problem": problem,
            "total": total,
            "gap": gap,
            "sanal_option": other is not None,
            "target": TARGET,
        }
        return w.page(request, "ayar_form.html", context, status=status)

    def preview_page(
        request: Request,
        setting: SettingRequest,
        edit: dict[str, str],
        *,
        changed: bool = False,
    ) -> Response:
        """`changed`: onayda sonuç farklı çıktı; yeni önizleme 409 ile gösterilir."""
        settings = view()
        today = w.time.today()
        plans = [plan_settings(w.conf, setting, today=today)]
        if setting.also_sanal and other is not None:
            plans.append(plan_settings(other, setting, today=today))
        if plans[0].problem is not None:
            return form_page(request, edit, problem=plans[0].problem, status=409)
        signed = None
        if all(plan.ready for plan in plans):
            fields = {
                "profil": w.profile,
                "islem": "ayar",
                **request_fields(setting, settings.classes),
            }
            for plan, name in zip(plans, ("sonuc", "sonuc_sanal"), strict=False):
                if plan.proposal is not None:
                    fields[name] = proposal_result(plan.proposal)
            signed = sign(w.key, request.state.session, fields, now=w.time.now())
        context: dict[str, object] = {
            **helpers(settings),
            "plans": plans,
            "signed": signed,
            "edit": edit,
            "changed": changed,
            "carry_option": any(p.proposal is not None and p.proposal.later for p in plans),
            "day": setting.day,
        }
        return w.page(request, "ayar_onizle.html", context, status=409 if changed else 200)

    def new_form(request: Request) -> Response:
        if (denied := gate(request, f"{prefix}/ayarlar/yeni")) is not None:
            return denied
        try:
            settings = view()
            values = form_values(settings.current, settings.classes, today=w.time.today())
            return form_page(request, values)
        except (PageError, *PAGE_ERRORS) as exc:
            return failure(request, str(exc), 503)

    def previewing(request: Request, form: dict[str, str]) -> Response:
        if (denied := gate(request, f"{prefix}/ayarlar/yeni")) is not None:
            return denied
        if form.get("duzenle") == "1":
            return form_page(request, form)
        settings = view()
        try:
            setting = read_setting_form(
                form, settings.classes, settings.labels, sanal_option=other is not None
            )
        except FormErrors as exc:
            return form_page(request, form, errors=exc.fields, status=400)
        return preview_page(request, setting, form)

    def edit_values(setting: SettingRequest) -> dict[str, str]:
        """Onayda sonuç değiştiyse "Düzenle" formu bugünkü ayarla ve girilen değişiklikle dolar."""
        settings = view()
        values = form_values(settings.current, settings.classes, today=w.time.today())
        return {**values, **request_fields(setting, settings.classes)}

    def other_outcome(
        setting: SettingRequest, fields: dict[str, str], nonce: str, carry: bool
    ) -> ProfileOutcome:
        """Gerçek profil yazıldıktan sonra sanal ayrı işlemde; hatası gerçeği geri almaz."""
        if other is None:
            raise TypeError("sanal profil yalnız gerçek profilde yazılır")
        try:
            return record_settings(
                other,
                setting,
                nonce=nonce,
                expected=fields.get("sonuc_sanal", ""),
                carry=carry,
                now=w.time.now(),
                today=w.time.today(),
            )
        except ResultChanged:
            return ProfileOutcome("sanal", "changed")
        except StorageBusyError:
            return ProfileOutcome("sanal", "busy")
        except (PageError, *PAGE_ERRORS) as exc:
            return ProfileOutcome("sanal", "failed", message=str(exc))

    def saving_setting(
        request: Request,
        fields: dict[str, str],
        nonce: str,
        carry: bool,
        signed_form: dict[str, str],
    ) -> Response:
        settings = view()
        try:
            setting = read_request_fields(fields, settings.classes, settings.labels)
        except FormErrors:
            return PlainTextResponse(REFUSED, status_code=403)
        if setting.also_sanal and other is None:
            return PlainTextResponse(REFUSED, status_code=403)
        try:
            outcome = record_settings(
                w.conf,
                setting,
                nonce=nonce,
                expected=fields.get("sonuc", ""),
                carry=carry,
                now=w.time.now(),
                today=w.time.today(),
            )
        except ResultChanged:
            return preview_page(request, setting, edit_values(setting), changed=True)
        except DomainError as exc:
            return failure(request, str(exc), 409)
        if not setting.also_sanal:
            if outcome.status == "duplicate":
                message = (
                    f"Bu onay zaten kullanıldı; ayar sürümü #{outcome.setting_id} olarak"
                    " kaydedildi."
                )
                return failure(request, message, 409)
            target = f"{prefix}/ayarlar?islem=ayar&no={outcome.setting_id}"
            return RedirectResponse(target, status_code=303)
        outcomes = [outcome, other_outcome(setting, fields, nonce, carry)]
        context: dict[str, object] = {**helpers(settings), "outcomes": outcomes, "retry": None}
        if outcomes[1].status == "busy":
            # Gerçek profilde nonce harcandı (tekrar yazmaz); sanal aynı onayla yeniden denenir.
            context["retry"] = {**signed_form, **({"sonrakilere": "1"} if carry else {})}
        return w.page(request, "ayar_sonuc.html", context)

    def cancel_page(
        request: Request,
        setting_id: int,
        *,
        reason: str = "",
        errors: dict[str, str] | None = None,
        confirm: bool = False,
        changed: bool = False,
        status: int = 200,
    ) -> Response:
        try:
            row = cancel_target(w.conf, setting_id, today=w.time.today())
        except DomainError as exc:
            return failure(request, str(exc), 409)
        signed = None
        if confirm:
            fields = {
                "profil": w.profile,
                "islem": "vazgec",
                "no": str(setting_id),
                "gerekce": reason,
                "sonuc": cancel_result(row.stored),
            }
            signed = sign(w.key, request.state.session, fields, now=w.time.now())
        context: dict[str, object] = {
            **helpers(view()),
            "mode": "onizle" if confirm else "form",
            "row": row,
            "reason": reason,
            "errors": errors or {},
            "signed": signed,
            "changed": changed,
        }
        return w.page(request, "ayar_vazgec.html", context, status=status)

    def cancel_form(request: Request) -> Response:
        setting_id: int = request.path_params["no"]
        if (denied := gate(request, f"{prefix}/ayarlar/{setting_id}/vazgec")) is not None:
            return denied
        try:
            return cancel_page(request, setting_id)
        except (PageError, *PAGE_ERRORS) as exc:
            return failure(request, str(exc), 503)

    def cancelling(request: Request, form: dict[str, str]) -> Response:
        setting_id: int = request.path_params["no"]
        if (denied := gate(request, f"{prefix}/ayarlar/{setting_id}/vazgec")) is not None:
            return denied
        reason = form.get("gerekce", "")
        if form.get("duzenle") == "1":
            return cancel_page(request, setting_id, reason=reason)
        try:
            reason = read_reason(form)
        except FormErrors as exc:
            return cancel_page(request, setting_id, reason=reason, errors=exc.fields, status=400)
        return cancel_page(request, setting_id, reason=reason, confirm=True)

    def saving_cancel(request: Request, fields: dict[str, str], nonce: str) -> Response:
        number = fields.get("no", "")
        if not (number.isascii() and number.isdigit()):
            return PlainTextResponse(REFUSED, status_code=403)
        setting_id = int(number)
        try:
            reason = read_reason(fields)
            recorded = record_cancel(
                w.conf,
                setting_id,
                reason=reason,
                nonce=nonce,
                expected=fields.get("sonuc", ""),
                now=w.time.now(),
                today=w.time.today(),
            )
        except FormErrors:
            return PlainTextResponse(REFUSED, status_code=403)
        except ResultChanged:
            reason = fields.get("gerekce", "")
            return cancel_page(
                request, setting_id, reason=reason, confirm=True, changed=True, status=409
            )
        except DomainError as exc:
            return failure(request, str(exc), 409)
        if recorded.duplicate:
            message = f"Bu onay zaten kullanıldı; ayar sürümü #{setting_id} için vazgeçildi."
            return failure(request, message, 409)
        target = f"{prefix}/ayarlar?islem=ayar-vazgec&no={setting_id}"
        return RedirectResponse(target, status_code=303)

    def saving(request: Request, form: dict[str, str]) -> Response:
        if (denied := gate(request, f"{prefix}/ayarlar")) is not None:
            return denied
        # Kutu önizlemede seçilir; imzalı değildir, iki sonuç da önizlemede listelendi.
        carry = form.pop("sonrakilere", "") == "1"
        verified = verify(w.key, request.state.session, form, now=w.time.now())
        if verified.status == "expired":
            return failure(request, EXPIRED, 400)
        fields = verified.fields
        if verified.status != "ok" or fields.get("profil") != w.profile:
            return PlainTextResponse(REFUSED, status_code=403)
        kind = fields.get("islem")
        if kind == "ayar":
            return saving_setting(request, fields, verified.nonce, carry, form)
        if kind == "vazgec":
            return saving_cancel(request, fields, verified.nonce)
        return PlainTextResponse(REFUSED, status_code=403)

    return [
        Route(f"{prefix}/ayarlar", settings_page, methods=["GET"]),
        Route(f"{prefix}/ayarlar/yeni", new_form, methods=["GET"]),
        Route(f"{prefix}/ayarlar/yeni", posted(previewing), methods=["POST"]),
        Route(f"{prefix}/ayarlar/kaydet", posted(saving), methods=["POST"]),
        Route(f"{prefix}/ayarlar/{{no:int}}/vazgec", cancel_form, methods=["GET"]),
        Route(f"{prefix}/ayarlar/{{no:int}}/vazgec", posted(cancelling), methods=["POST"]),
    ]
