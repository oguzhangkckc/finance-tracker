"""Yazma uçlarının ortak parçası (K-137): profil, saat, onay anahtarı ve Access e-postası.

Onay jetonu oturuma değil e-postaya (harf duyarsız) bağlıdır. Geçersiz imza, başka profilin ya
da başka eylemin onayı 403'tür ve nedeni günlüğe yazılır; süresi dolmuş onay 422'dir."""

import logging
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Path
from starlette.responses import Response

from finans.api.context import ApiContext, context, viewer
from finans.api.encoding import CanonicalJSONResponse, error_response
from finans.api.errors import INVALID
from finans.api.writing import ConfirmInput, Saved
from finans.ports.clock import Clock
from finans.settings import Settings
from finans.sunum.confirm import Verified, sign, verify
from finans.sunum.profiles import BY_SLUG, ProfileSlug

REFUSED: Final = "İstek reddedildi."
EXPIRED: Final = (
    "Önizleme 10 dakikadan eski; onay süresi doldu, hiçbir şey kaydedilmedi. Yeniden önizle."
)
_LOG = logging.getLogger("finans.api")


@dataclass(frozen=True, slots=True)
class Writer:
    conf: Settings
    slug: ProfileSlug
    clock: Clock
    session: str
    key: bytes
    # Gerçek profilde "sanal portföye de uygula" için sanal profilin ayarları (K-127).
    other: Settings | None

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
    profile = BY_SLUG[profil]
    return Writer(
        conf=ctx.profiles[profile],
        slug=profil,
        clock=ctx.clock,
        session=email.casefold(),
        key=ctx.api.confirm_key.get_secret_value().encode(),
        other=ctx.profiles["sanal"] if profile == "real" else None,
    )


W = Annotated[Writer, Depends(writer)]


def invalid(fields: dict[str, str]) -> Response:
    """`fields` JSON alan adlarıyladır."""
    return error_response(422, INVALID, fields)


def refused(w: Writer, reason: str) -> Response:
    _LOG.warning("Onay reddedildi (%s): %s", w.slug, reason)
    return error_response(403, REFUSED)


def confirmed(w: Writer, body: ConfirmInput, kind: str) -> Verified | Response:
    verified = verify(w.key, w.session, body.confirmation, now=w.clock.now())
    if verified.status == "expired":
        return error_response(422, EXPIRED)
    if verified.status != "ok":
        return refused(w, "imza geçersiz")
    if verified.fields.get("profil") != w.slug:
        return refused(w, "başka profilin onayı")
    if verified.fields.get("islem") != kind:
        return refused(w, "başka bir işlemin onayı")
    return verified


def saved(number: int, duplicate: bool) -> Response:
    return CanonicalJSONResponse(Saved(number=number, duplicate=duplicate))
