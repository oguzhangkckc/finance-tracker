"""Ayar yazmalarının girdileri ve yanıtları (K-127, K-137, K-138).

Gönderilmeyen (null) ayar değişmez: yürürlük gününde geçerli değeriyle kalır. Gönderilen değer
bugün geçerli olanla aynıysa değişmiş sayılmaz; web formundaki `onceki_` alanlarının yaptığı budur.
Hedefler yüzdedir ve her sınıf için verilir. Sonraki sürümlere taşıma seçimi (`carry`) önizlemenin
girdisidir ve onayla imzalanır; seçim değişirse yeniden önizlenir."""

from collections.abc import Sequence
from datetime import date
from typing import Final, Literal

from pydantic import Field

from finans.api.models import Model
from finans.api.pages import SettingChange, SettingItem, SettingValuesData, setting_values
from finans.api.writing import TEXT_MAX
from finans.application.settings import LaterRewrite
from finans.domain.settings import SettingField, SettingVersion
from finans.sunum.profiles import SLUGS, ProfileSlug
from finans.sunum.setting_writes import (
    PREVIOUS,
    TARGET,
    ProfileOutcome,
    ProfilePlan,
    SettingsView,
    change_lines,
    form_values,
    kept_text,
)

# Web formunun alan adı → JSON alan adı; `hedef_<sınıf>` alanları `targets.<sınıf>` olur.
SETTING_FIELDS: Final = {
    "gun": "day",
    "maas_gunu": "payday",
    "katki": "contribution",
    "hedef": "targets",
    "degisen": "changed",
    "gerekce": "reason",
}


def setting_json_fields(fields: dict[str, str]) -> dict[str, str]:
    return {
        f"targets.{name.removeprefix(TARGET)}"
        if name.startswith(TARGET)
        else SETTING_FIELDS.get(name, name): message
        for name, message in fields.items()
    }


class SettingInput(Model):
    day: str = Field(default="", max_length=TEXT_MAX)
    payday: str | None = Field(default=None, max_length=TEXT_MAX)
    contribution: str | None = Field(default=None, max_length=TEXT_MAX)
    targets: dict[str, str] | None = None
    also_sanal: bool = False
    carry: bool = False

    def unknown_classes(self, classes: Sequence[str]) -> dict[str, str]:
        given = self.targets or {}
        return {
            f"targets.{code}": "Portföyde bu sınıf yok." for code in given if code not in classes
        }

    def form(self, view: SettingsView, today: date) -> dict[str, str]:
        current = form_values(view.current, view.classes, today=today)
        form = {"gun": self.day, "sanala": "1" if self.also_sanal else ""}
        edited: dict[str, str] = {}
        if self.payday is not None:
            edited["maas_gunu"] = self.payday
        if self.contribution is not None:
            edited["katki"] = self.contribution
        if self.targets is not None:
            edited |= {f"{TARGET}{c}": self.targets.get(c, "") for c in view.classes}
        for name, text in edited.items():
            form[name] = text
            form[f"{PREVIOUS}{name}"] = current[name]
        return form


class VersionData(Model):
    """`initial`: `ft config apply`'ın yazdığı başlangıç sürümü; yürürlük günü yoktur."""

    effective_from: date
    initial: bool
    values: SettingValuesData


def version_data(version: SettingVersion) -> VersionData:
    return VersionData(
        effective_from=version.effective_from,
        initial=version.effective_from.year == 1,
        values=setting_values(version),
    )


def _changes(
    before: SettingVersion | None,
    after: SettingVersion,
    fields: Sequence[SettingField],
    view: SettingsView,
) -> list[SettingChange]:
    return [
        SettingChange(setting=name, change=text)
        for name, text in change_lines(before, after, fields, view)
    ]


class LaterVersion(Model):
    """Değişikliği taşımayan planlanmış sürüm: `kept` taşınmazsa o günden geçerli olacak değerler,
    `carried` taşınırsa yazılacak değişiklik."""

    id: int
    effective_from: date
    fields: list[SettingField]
    kept: str
    carried: list[SettingChange]


def later_version(later: LaterRewrite, view: SettingsView) -> LaterVersion:
    stored = later.stored
    return LaterVersion(
        id=stored.id,
        effective_from=stored.version.effective_from,
        fields=list(later.fields),
        kept=kept_text(stored, later.fields, view),
        carried=_changes(stored.version, later.rewritten, later.fields, view),
    )


class ProfileProposal(Model):
    """`problem`: bu profilde önizleme yapılamadı (ör. başlangıç sürümü yok). `issues`
    kaydı engeller; `ready` ancak ikisi de yoksa doğrudur."""

    profile: ProfileSlug
    problem: str | None
    version: VersionData | None
    base: VersionData | None
    changed_fields: list[SettingField]
    changes: list[SettingChange]
    issues: list[str]
    later: list[LaterVersion]
    ready: bool


def profile_proposal(plan: ProfilePlan, view: SettingsView) -> ProfileProposal:
    proposal = plan.proposal
    if proposal is None:
        return ProfileProposal(
            profile=SLUGS[plan.profile],
            problem=plan.problem,
            version=None,
            base=None,
            changed_fields=[],
            changes=[],
            issues=[],
            later=[],
            ready=False,
        )
    return ProfileProposal(
        profile=SLUGS[plan.profile],
        problem=plan.problem,
        version=version_data(proposal.version),
        base=version_data(proposal.base),
        changed_fields=list(proposal.changed),
        changes=_changes(proposal.base, proposal.version, proposal.changed, view),
        issues=[str(issue) for issue in proposal.issues],
        later=[later_version(later, view) for later in proposal.later],
        ready=plan.ready,
    )


class SettingPreviewBody(Model):
    """`confirmation` yalnız bütün profillerin planı hazırsa verilir. `changed`: onayda sonuç
    önizlemeden farklı çıktı, kayıt yapılmadı; bu yeni önizlemedir."""

    day: date
    plans: list[ProfileProposal]
    carry_option: bool
    carry: bool
    confirmation: dict[str, str] | None
    changed: bool


class RewrittenPair(Model):
    cancelled: int
    written: int


class ProfileResult(Model):
    """Her profil ayrı işlemde yazılır; sanalın sonucu gerçeği geri almaz. `busy`: sanal
    veritabanı meşguldü; aynı onay yeniden gönderilirse gerçek tekrar yazılmaz, sanal denenir."""

    profile: ProfileSlug
    status: Literal["saved", "duplicate", "changed", "busy", "failed"]
    setting_id: int | None
    rewritten: list[RewrittenPair]
    message: str


def profile_result(outcome: ProfileOutcome) -> ProfileResult:
    return ProfileResult(
        profile=SLUGS[outcome.profile],
        status=outcome.status,
        setting_id=outcome.setting_id,
        rewritten=[RewrittenPair(cancelled=old, written=new) for old, new in outcome.rewritten],
        message=outcome.message,
    )


class SettingSaved(Model):
    outcomes: list[ProfileResult]


class CancelPreviewBody(Model):
    profile: ProfileSlug
    target: SettingItem
    reason: str
    confirmation: dict[str, str]
    changed: bool
