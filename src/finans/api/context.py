"""Uçların ortak durumu: uygulama kurulurken bir kez oluşturulur, uçlara Depends ile gelir."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Path, Request

from finans.ports.clock import Clock
from finans.settings import ApiSettings, Profile, Settings
from finans.sunum.profiles import BY_SLUG, ProfileSlug


@dataclass(frozen=True, slots=True)
class ApiContext:
    settings: Settings
    """Profili çözülmemiş ayarlar; `settings.profile` açılış profilidir (K-125)."""
    api: ApiSettings
    clock: Clock
    profiles: Mapping[Profile, Settings]


def context(request: Request) -> ApiContext:
    return cast(ApiContext, request.app.state.context)


def viewer(request: Request) -> str:
    """RequireAccess'in doğruladığı e-posta."""
    return cast(str, request.state.email)


def profile(
    profil: Annotated[ProfileSlug, Path(description="Profil (K-125)")],
    ctx: Annotated[ApiContext, Depends(context)],
) -> Settings:
    """Profilin çözülmüş ayarları; bilinmeyen profil 404 olur (errors)."""
    return ctx.profiles[BY_SLUG[profil]]
