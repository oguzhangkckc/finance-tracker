"""Testlerde Access jetonu: yerelde üretilen RSA anahtarıyla imzalanır, ağa çıkılmaz."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from types import MappingProxyType

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from finans.settings import ApiSettings

TEAM_DOMAIN = "xht-takim.cloudflareaccess.com"
AUDIENCE = "xht-aud-0123456789abcdef"
EMAIL = "kullanici@example.com"
ORIGIN = "https://finans.example.com"
KID = "anahtar-1"
CONFIRM_KEY = "o" * 64
LIFETIME = timedelta(hours=24)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

API_SETTINGS = ApiSettings(
    host="127.0.0.1",
    port=8765,
    team_domain=TEAM_DOMAIN,
    audience=AUDIENCE,
    allowed_email=EMAIL,
    origin=ORIGIN,
    confirm_key=SecretStr(CONFIRM_KEY),
    # Testler makinede derlenmiş bir arayüz olup olmamasına bağlı kalmasın.
    dist=Path(__file__).with_name("derlenmis-arayuz-yok"),
)


@cache
def private_key(name: str = "ana") -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(name: str = "ana", *, kid: str = KID) -> dict[str, object]:
    document: dict[str, object] = json.loads(RSAAlgorithm.to_jwk(private_key(name).public_key()))
    document.update(kid=kid, alg="RS256", use="sig")
    return document


def seconds(moment: datetime) -> int:
    return (moment - _EPOCH) // timedelta(seconds=1)


def access_token(
    now: datetime,
    *,
    key: str = "ana",
    kid: str | None = KID,
    drop: tuple[str, ...] = (),
    extra: Mapping[str, object] = MappingProxyType({}),
    **claims: object,
) -> str:
    """Cloudflare'in jetonu gibi: `aud` liste, `iss` takım adresi; `extra` ve `claims` alanları
    ezer."""
    payload: dict[str, object] = {
        "aud": [AUDIENCE],
        "iss": f"https://{TEAM_DOMAIN}",
        "email": EMAIL,
        "iat": seconds(now),
        "nbf": seconds(now),
        "exp": seconds(now + LIFETIME),
        "sub": "xht-kullanici",
        "type": "app",
        **extra,
        **claims,
    }
    for name in drop:
        payload.pop(name)
    headers = {} if kid is None else {"kid": kid}
    return jwt.encode(payload, private_key(key), algorithm="RS256", headers=headers)
