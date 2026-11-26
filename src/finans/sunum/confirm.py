"""Onay formu imzası (K-126): oturuma bağlı, 10 dakika geçerli, tek kullanımlık nonce taşır.
İmzalı alanlar önizlemenin girdisi ve sonucudur; kayıtta girdi yeniden doğrulanır."""

import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Final, Literal
from urllib.parse import urlencode

VALID_FOR: Final = timedelta(minutes=10)
# Saatler aynı makinede; küçük bir pay yalnızca saniye yuvarlaması içindir.
CLOCK_SKEW: Final = timedelta(minutes=1)
NONCE_FIELD: Final = "nonce"
TIME_FIELD: Final = "zaman"
SIGNATURE_FIELD: Final = "imza"


@dataclass(frozen=True, slots=True)
class Verified:
    status: Literal["ok", "invalid", "expired"]
    fields: dict[str, str] = field(default_factory=dict)
    nonce: str = ""


def _mac(key: bytes, session: str, fields: Mapping[str, str]) -> str:
    canonical = urlencode(sorted(fields.items()))
    return hmac.new(key, f"onay:{session}:{canonical}".encode(), sha256).hexdigest()


def sign(key: bytes, session: str, fields: Mapping[str, str], *, now: datetime) -> dict[str, str]:
    signed = {
        **fields,
        NONCE_FIELD: secrets.token_urlsafe(24),
        TIME_FIELD: str(int(now.timestamp())),
    }
    return {**signed, SIGNATURE_FIELD: _mac(key, session, signed)}


def verify(key: bytes, session: str, form: Mapping[str, str], *, now: datetime) -> Verified:
    signature = form.get(SIGNATURE_FIELD, "")
    signed = {name: value for name, value in form.items() if name != SIGNATURE_FIELD}
    # compare_digest ASCII dışı str'de TypeError verir; formdan her şey gelebilir.
    if not hmac.compare_digest(_mac(key, session, signed).encode(), signature.encode()):
        return Verified("invalid")
    issued = datetime.fromtimestamp(int(signed[TIME_FIELD]), tz=now.tzinfo)
    if not issued - CLOCK_SKEW <= now <= issued + VALID_FOR:
        return Verified("expired")
    nonce = signed.pop(NONCE_FIELD)
    signed.pop(TIME_FIELD)
    return Verified("ok", signed, nonce)
