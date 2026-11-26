from typing import Annotated

from fastapi import APIRouter, Depends

from finans.api.context import ApiContext, context, viewer
from finans.api.models import ERROR_RESPONSES, Health, ProfileLink, Session
from finans.settings import PROFILES
from finans.sunum.profiles import PROFILE_LABELS, SLUGS

public = APIRouter(prefix="/api", tags=["ortak"])
router = APIRouter(prefix="/api", tags=["ortak"], responses=ERROR_RESPONSES)


@public.get("/saglik")
def health() -> Health:
    """Kimlik istemez ve bilgi vermez; deploy betiğinin sağlık denetimi bunu yoklar (K-140)."""
    return Health(status="ok")


@router.get("/oturum")
def session(
    ctx: Annotated[ApiContext, Depends(context)], email: Annotated[str, Depends(viewer)]
) -> Session:
    return Session(
        email=email,
        profiles=[ProfileLink(slug=SLUGS[p], label=PROFILE_LABELS[p]) for p in PROFILES],
        default_profile=SLUGS[ctx.settings.profile],
    )
