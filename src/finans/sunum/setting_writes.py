"""Web'den ayar sürümü (K-127): form → önizleme → imzalı onay → kayıt. Hedefler yüzdeyle girilir,
oran saklanır. Gerçek profilde aynı değişiklik isteğe bağlı olarak sanal portföye de yazılır;
iki veritabanına ayrı işlemlerle, her profilin sonucu ayrı. Kurallar application'dadır."""

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final, Literal

from finans import bootstrap
from finans.application.inputs import InputError, parse_amount, parse_day
from finans.application.settings import (
    KEEP,
    HistoryRow,
    Keep,
    Proposal,
    cancel_version,
    cancellable,
    propose,
    save_proposal,
    setting_history,
)
from finans.contracts.display import class_label, money
from finans.domain.models import ZERO
from finans.domain.numeric import canonical_text
from finans.domain.settings import FIELD_LABELS, SettingField, SettingValues, SettingVersion
from finans.ports.repositories import StoredSetting
from finans.settings import Profile, Settings
from finans.sunum.views import load_config
from finans.sunum.writes import FormErrors, Recorded, ResultChanged

EDITABLE: Final = ("maas_gunu", "katki", "hedef")
PREVIOUS: Final = "onceki_"
TARGET: Final = "hedef_"
HUNDRED: Final = Decimal(100)
REASON_MAX: Final = 200
_LOG = logging.getLogger("finans.sunum")


@dataclass(frozen=True, slots=True)
class SettingRequest:
    """Değiştirilmeyen ayar `KEEP`'tir: yürürlük gününde geçerli olan değeriyle kalır."""

    day: date
    payday: int | Keep = KEEP
    contribution: Decimal | Keep = KEEP
    targets: Mapping[str, Decimal] | Keep = KEEP
    also_sanal: bool = False

    @property
    def edited(self) -> tuple[str, ...]:
        given = (self.payday, self.contribution, self.targets)
        return tuple(name for name, value in zip(EDITABLE, given, strict=True) if value is not KEEP)


def _field(form: Mapping[str, str], name: str) -> str:
    return form.get(name, "").strip()


def _comma(value: Decimal) -> str:
    return canonical_text(value).replace(".", ",")


def percent_text(ratio: Decimal) -> str:
    """Oran yüzde olarak, yuvarlamadan: 0.175 → "17,5"."""
    return _comma(ratio.scaleb(2))


def form_values(values: SettingValues, classes: Sequence[str], *, today: date) -> dict[str, str]:
    """Form o günkü ayarla dolar; `onceki_` alanları neyin değiştirildiğini ayırmak içindir."""
    contribution = values.monthly_contribution
    shown = {
        "maas_gunu": "" if values.payday is None else str(values.payday),
        "katki": "" if contribution is None else _comma(contribution),
        **{f"{TARGET}{c}": percent_text(values.targets.get(c, ZERO)) for c in classes},
    }
    previous = {f"{PREVIOUS}{name}": value for name, value in shown.items()}
    return {"gun": today.isoformat(), **shown, **previous}


def _payday(form: Mapping[str, str], errors: dict[str, str]) -> int | Keep:
    text, before = _field(form, "maas_gunu"), _field(form, f"{PREVIOUS}maas_gunu")
    if not text:
        if before:
            errors["maas_gunu"] = "Maaş günü boş bırakılamaz."
        return KEEP
    if not (text.isascii() and text.isdigit() and 1 <= int(text) <= 31):
        errors["maas_gunu"] = "Maaş günü 1 ile 31 arasında bir gün olmalı."
        return KEEP
    return KEEP if text == before else int(text)


def _decimal(text: str, label: str) -> Decimal | None:
    try:
        value = parse_amount(label, text, decimal=",")
    except InputError:
        return None
    return value if value.is_finite() else None


def _contribution(form: Mapping[str, str], errors: dict[str, str]) -> Decimal | Keep:
    text, before = _field(form, "katki"), _field(form, f"{PREVIOUS}katki")
    if not text:
        if before:
            errors["katki"] = "Aylık katkı boş bırakılamaz."
        return KEEP
    try:
        value = parse_amount("Aylık katkı", text, decimal=",")
    except InputError as exc:
        errors["katki"] = str(exc)
        return KEEP
    if not value.is_finite() or value < 0:
        errors["katki"] = "Aylık katkı negatif olamaz."
        return KEEP
    previous = _decimal(before, "Aylık katkı") if before else None
    return KEEP if previous == value else value


def total_text(total: Decimal) -> str:
    """ "%2,5 eksik" ya da "%2,5 fazla"; toplam tam %100 ise boş."""
    if total == HUNDRED:
        return ""
    word = "eksik" if total < HUNDRED else "fazla"
    return f"%{_comma(abs(HUNDRED - total))} {word}"


def form_total(values: Mapping[str, str], classes: Sequence[str]) -> tuple[str, str]:
    """Formdaki hedeflerin toplamı ve farkı; betik yokken de ilk hâli görünür."""
    total = ZERO
    for code in classes:
        value = _decimal(_field(values, f"{TARGET}{code}"), code)
        if value is None:
            return "?", "bir alan sayı değil"
        total += value
    return _comma(total), total_text(total)


def _targets(
    form: Mapping[str, str],
    classes: Sequence[str],
    labels: Mapping[str, str],
    errors: dict[str, str],
) -> Mapping[str, Decimal] | Keep:
    texts = {c: _field(form, f"{TARGET}{c}") for c in classes}
    befores = {c: _field(form, f"{PREVIOUS}{TARGET}{c}") for c in classes}
    if not any(texts.values()) and not any(befores.values()):
        return KEEP
    percents: dict[str, Decimal] = {}
    for code, text in texts.items():
        name, label = f"{TARGET}{code}", class_label(code, labels)
        if not text:
            errors[name] = f"{label} boş bırakılamaz; hedef yoksa 0 yaz."
            continue
        try:
            value = parse_amount(label, text, decimal=",")
        except InputError as exc:
            errors[name] = str(exc)
            continue
        if not (value.is_finite() and ZERO <= value <= HUNDRED):
            errors[name] = f"{label}: yüzde 0 ile 100 arasında olmalı."
            continue
        percents[code] = value
    if len(percents) != len(classes):
        return KEEP
    total = sum(percents.values(), ZERO)
    if total != HUNDRED:
        errors["hedef"] = (
            f"Hedeflerin toplamı %{_comma(total)}; {total_text(total)}. Toplam tam %100 olmalı."
        )
        return KEEP
    previous = {code: _decimal(text, code) for code, text in befores.items()}
    if previous == percents:
        return KEEP
    return {code: value.scaleb(-2) for code, value in percents.items()}


def read_setting_form(
    form: Mapping[str, str],
    classes: Sequence[str],
    labels: Mapping[str, str],
    *,
    sanal_option: bool,
) -> SettingRequest:
    errors: dict[str, str] = {}
    day = None
    try:
        day = parse_day(_field(form, "gun"))
    except InputError as exc:
        errors["gun"] = str(exc)
    payday = _payday(form, errors)
    contribution = _contribution(form, errors)
    targets = _targets(form, classes, labels, errors)
    if errors or day is None:
        raise FormErrors(errors)
    also_sanal = sanal_option and _field(form, "sanala") == "1"
    return SettingRequest(day, payday, contribution, targets, also_sanal)


def request_fields(request: SettingRequest, classes: Sequence[str]) -> dict[str, str]:
    """İmzalanan girdi: yalnız değiştirilen ayarlar; onayda `read_request_fields` okur."""
    fields = {
        "gun": request.day.isoformat(),
        "degisen": " ".join(request.edited),
        "sanala": "1" if request.also_sanal else "",
    }
    if not isinstance(request.payday, Keep):
        fields["maas_gunu"] = str(request.payday)
    if not isinstance(request.contribution, Keep):
        fields["katki"] = _comma(request.contribution)
    if not isinstance(request.targets, Keep):
        fields |= {f"{TARGET}{c}": percent_text(request.targets[c]) for c in classes}
    return fields


def read_request_fields(
    fields: Mapping[str, str], classes: Sequence[str], labels: Mapping[str, str]
) -> SettingRequest:
    """Değiştirilmeyen ayarın alanı boş gelir; `read_setting_form` onu KEEP okur."""
    edited = set(_field(fields, "degisen").split())
    if not edited <= set(EDITABLE):
        raise FormErrors({"degisen": "Bilinmeyen ayar."})
    form = {"gun": _field(fields, "gun"), "sanala": _field(fields, "sanala")}
    if "maas_gunu" in edited:
        form["maas_gunu"] = _field(fields, "maas_gunu")
    if "katki" in edited:
        form["katki"] = _field(fields, "katki")
    if "hedef" in edited:
        form |= {f"{TARGET}{c}": _field(fields, f"{TARGET}{c}") for c in classes}
    request = read_setting_form(form, classes, labels, sanal_option=True)
    if set(request.edited) != edited:
        raise FormErrors({"degisen": "İmzalı alanlar eksik."})
    return request


@dataclass(frozen=True, slots=True)
class ProfilePlan:
    """`problem`: bu profilde önizleme yapılamadı (ör. başlangıç sürümü yok)."""

    profile: Profile
    proposal: Proposal | None
    problem: str | None = None

    @property
    def ready(self) -> bool:
        return self.proposal is not None and not self.proposal.issues


def plan_settings(conf: Settings, request: SettingRequest, *, today: date) -> ProfilePlan:
    try:
        config = load_config(conf)
        with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
            proposal = propose(
                uow,
                config,
                effective_from=request.day,
                today=today,
                payday=request.payday,
                contribution=request.contribution,
                targets=request.targets,
            )
    except (bootstrap.SetupError, bootstrap.ProfileError, ValueError) as exc:
        return ProfilePlan(conf.profile, None, str(exc))
    return ProfilePlan(conf.profile, proposal)


def _version_text(version: SettingVersion) -> str:
    contribution = version.monthly_contribution
    targets = {name: canonical_text(value) for name, value in version.targets.items()}
    return "|".join(
        (
            version.effective_from.isoformat(),
            "" if version.payday is None else str(version.payday),
            "" if contribution is None else canonical_text(contribution),
            json.dumps(targets, sort_keys=True),
        )
    )


def proposal_result(proposal: Proposal) -> str:
    """Onay formunun imzaladığı sonuç; sonraki sürümlerin listesi de içindedir."""
    parts = [
        _version_text(proposal.version),
        _version_text(proposal.base),
        ",".join(proposal.changed),
        *(str(issue) for issue in proposal.issues),
        *(f"{later.stored.id}:{_version_text(later.rewritten)}" for later in proposal.later),
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfileOutcome:
    profile: Profile
    status: Literal["saved", "duplicate", "changed", "busy", "failed"]
    setting_id: int | None = None
    rewritten: tuple[tuple[int, int], ...] = ()
    message: str = ""


def record_settings(
    conf: Settings,
    request: SettingRequest,
    *,
    nonce: str,
    expected: str,
    carry: bool,
    now: datetime,
    today: date,
) -> ProfileOutcome:
    """Bu profilin veritabanında tek işlem: önizlemeyle aynı sonuç, kayıt ve nonce."""
    config = load_config(conf)
    with bootstrap.open_unit_of_work(conf, migrate=False) as uow:
        used = uow.submissions.used(nonce)
        if used is not None:
            return ProfileOutcome(conf.profile, "duplicate", int(used))
        proposal = propose(
            uow,
            config,
            effective_from=request.day,
            today=today,
            payday=request.payday,
            contribution=request.contribution,
            targets=request.targets,
        )
        if proposal_result(proposal) != expected:
            raise ResultChanged
        saved = save_proposal(
            uow, config, proposal, source="web", today=today, at=now, carry_later=carry
        )
        uow.submissions.record(nonce, ref=str(saved.setting_id), at=now)
    # K-126: log'a tutar ve oran yazılmaz; yalnız hangi ayarın değiştiği.
    _LOG.info(
        "Ayar sürümü kaydedildi: #%d %s; sonraki sürümlere taşınan: %d (%s)",
        saved.setting_id,
        ", ".join(FIELD_LABELS[field] for field in proposal.changed),
        len(saved.rewritten),
        conf.profile,
    )
    return ProfileOutcome(conf.profile, "saved", saved.setting_id, saved.rewritten)


@dataclass(frozen=True, slots=True)
class SettingsView:
    """`current`: bugün geçerli sürüm; sürüm yoksa portfolio.toml."""

    history: list[HistoryRow]
    current: SettingValues
    current_row: HistoryRow | None
    planned: list[HistoryRow]
    classes: tuple[str, ...]
    labels: Mapping[str, str]

    def cls(self, code: str) -> str:
        return class_label(code, self.labels)


def settings_view(conf: Settings, today: date) -> SettingsView:
    config = load_config(conf)
    with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
        history = setting_history(uow, today=today)
    current_row = next((row for row in history if row.state == "in_force"), None)
    current: SettingValues = config if current_row is None else current_row.stored.version
    planned = [row for row in history if row.state == "planned"]
    return SettingsView(
        history, current, current_row, planned, tuple(config.targets), config.class_labels
    )


def value_text(values: SettingValues, field: SettingField, view: SettingsView) -> str:
    if field == "payday":
        return "tanımlı değil" if values.payday is None else str(values.payday)
    if field == "monthly_contribution":
        amount = values.monthly_contribution
        return "tanımlı değil" if amount is None else money(amount)
    return ", ".join(
        f"{view.cls(c)} %{percent_text(values.targets.get(c, ZERO))}" for c in view.classes
    )


def change_lines(
    previous: SettingVersion | None,
    version: SettingVersion,
    fields: Sequence[SettingField],
    view: SettingsView,
) -> list[tuple[str, str]]:
    """(ayar, değişiklik) çiftleri; başlangıç sürümünde üç ayarın değeri."""

    def label(field: SettingField) -> str:
        return FIELD_LABELS[field].capitalize()

    if previous is None:
        every: tuple[SettingField, ...] = ("payday", "monthly_contribution", "targets")
        return [(label(f), value_text(version, f, view)) for f in every]
    lines: list[tuple[str, str]] = []
    for field in fields:
        if field == "targets":
            moved = [
                f"{view.cls(c)} %{percent_text(previous.targets.get(c, ZERO))}"
                f" → %{percent_text(version.targets.get(c, ZERO))}"
                for c in view.classes
                if previous.targets.get(c) != version.targets.get(c)
            ]
            lines.append((label(field), ", ".join(moved)))
        else:
            old, new = value_text(previous, field, view), value_text(version, field, view)
            lines.append((label(field), f"{old} → {new}"))
    return lines


def kept_text(stored: StoredSetting, fields: Sequence[SettingField], view: SettingsView) -> str:
    """Sonraki sürümün geri getireceği değerler: "aylık katkı 1.000,00 TL"."""
    return " ve ".join(f"{FIELD_LABELS[f]} {value_text(stored.version, f, view)}" for f in fields)


def read_reason(form: Mapping[str, str]) -> str:
    reason = _field(form, "gerekce")
    if not reason:
        raise FormErrors({"gerekce": "Gerekçe boş bırakılamaz; neden vazgeçildiği kayıtta kalır."})
    if len(reason) > REASON_MAX:
        raise FormErrors({"gerekce": f"Gerekçe en fazla {REASON_MAX} karakter olabilir."})
    return reason


def cancel_target(conf: Settings, setting_id: int, *, today: date) -> HistoryRow:
    with bootstrap.open_unit_of_work(conf, readonly=True) as uow:
        stored = cancellable(uow, setting_id, today=today)
        history = setting_history(uow, today=today)
    return next(row for row in history if row.stored.id == stored.id)


def cancel_result(stored: StoredSetting) -> str:
    text = f"{stored.id}\n{_version_text(stored.version)}"
    return hashlib.sha256(text.encode()).hexdigest()


def record_cancel(
    conf: Settings,
    setting_id: int,
    *,
    reason: str,
    nonce: str,
    expected: str,
    now: datetime,
    today: date,
) -> Recorded:
    with bootstrap.open_unit_of_work(conf, migrate=False) as uow:
        used = uow.submissions.used(nonce)
        if used is not None:
            return Recorded(int(used), duplicate=True)
        if cancel_result(cancellable(uow, setting_id, today=today)) != expected:
            raise ResultChanged
        cancel_version(uow, setting_id, reason=reason, today=today, at=now)
        uow.submissions.record(nonce, ref=str(setting_id), at=now)
    _LOG.info("Ayar sürümünden vazgeçildi: #%d (%s)", setting_id, conf.profile)
    return Recorded(setting_id, duplicate=False)
