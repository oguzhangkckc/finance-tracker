"""Uçların ortak durumu: uygulama kurulurken bir kez oluşturulur, uçlara Depends ile gelir."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request

from finans.ports.clock import Clock
from finans.settings import ApiSettings, Profile, Settings


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
