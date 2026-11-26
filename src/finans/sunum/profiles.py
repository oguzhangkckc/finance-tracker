"""Profillerin adres adı ve etiketi; web ve API aynısını kullanır (K-125)."""

from typing import Final, Literal

from finans.settings import Profile

type ProfileSlug = Literal["gercek", "sanal"]
SLUGS: Final[dict[Profile, ProfileSlug]] = {"real": "gercek", "sanal": "sanal"}
PROFILE_LABELS: Final[dict[Profile, str]] = {"real": "Gerçek", "sanal": "Sanal"}
BY_SLUG: Final[dict[ProfileSlug, Profile]] = {slug: profile for profile, slug in SLUGS.items()}
