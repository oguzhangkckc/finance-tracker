"""Cloudflare Access JWT doğrulaması (K-136). Reddin nedeni yalnız log'a gider.

Zaman alanları PyJWT'ye bırakılmaz, çünkü o duvar saatine kendisi bakar; aynı kurallar Clock ile
uygulanır. İmza, `aud` ve `iss` PyJWT'dedir."""

import logging
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

import jwt

from finans.ports.access import AccessKeyError, AccessKeySource
from finans.ports.clock import Clock
from finans.settings import ApiSettings

ALGORITHM: Final = "RS256"
LEEWAY_SECONDS: Final = 30
REFRESH_INTERVAL: Final = timedelta(minutes=5)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_SECOND: Final = timedelta(seconds=1)
_LOG = logging.getLogger("finans.api")


class AccessDenied(Exception):
    """İletisi log içindir; jeton ve e-posta iletiye girmez."""


class KeyCache:
    """Bilinmeyen `kid` önbelleği en çok 5 dakikada bir yeniler; yenileme başarısızsa eski
    anahtarlar kalır, önbellek boşsa istek reddedilir (fail closed)."""

    def __init__(self, source: AccessKeySource, clock: Clock) -> None:
        self._source = source
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._attempted: datetime | None = None
        self._lock = threading.Lock()

    def prefetch(self) -> None:
        with self._lock:
            self._refresh()

    def key(self, kid: str) -> jwt.PyJWK | None:
        known = self._keys.get(kid)
        if known is not None:
            return known
        with self._lock:
            known = self._keys.get(kid)
            if known is None and self._may_refresh():
                self._refresh()
                known = self._keys.get(kid)
            return known

    def _may_refresh(self) -> bool:
        attempted = self._attempted
        return attempted is None or self._clock.now() - attempted >= REFRESH_INTERVAL

    def _refresh(self) -> None:
        self._attempted = self._clock.now()
        try:
            documents = self._source.fetch()
        except AccessKeyError as error:
            _LOG.warning("Access anahtarları alınamadı: %s", error)
            return
        keys = _usable(documents)
        if not keys:
            _LOG.warning("Access anahtar listesinde kullanılabilir %s anahtarı yok", ALGORITHM)
            return
        self._keys = keys


def _usable(documents: tuple[Mapping[str, object], ...]) -> dict[str, jwt.PyJWK]:
    keys: dict[str, jwt.PyJWK] = {}
    for document in documents:
        kid = document.get("kid")
        if not isinstance(kid, str) or not kid or document.get("kty") != "RSA":
            continue
        if document.get("use", "sig") != "sig" or document.get("alg", ALGORITHM) != ALGORITHM:
            continue
        try:
            keys[kid] = jwt.PyJWK(dict(document), algorithm=ALGORITHM)
        except jwt.PyJWTError:
            continue
    return keys


class AccessVerifier:
    def __init__(self, settings: ApiSettings, keys: KeyCache, clock: Clock) -> None:
        self._settings = settings
        self._keys = keys
        self._clock = clock

    def verify(self, token: str | None) -> str:
        """`Cf-Access-Jwt-Assertion` geçerliyse jetondaki e-posta; değilse AccessDenied."""
        if not token:
            raise AccessDenied("başlık yok")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AccessDenied("jeton çözülemedi") from None
        if header.get("alg") != ALGORITHM:
            raise AccessDenied("beklenmeyen imza algoritması")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AccessDenied("anahtar kimliği yok")
        key = self._keys.key(kid)
        if key is None:
            raise AccessDenied("anahtar bulunamadı")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={
                    "require": ["exp", "iat", "aud", "iss"],
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
        except jwt.PyJWTError as error:
            raise AccessDenied(type(error).__name__) from None
        _check_times(claims, self._clock.now())
        email = claims.get("email")
        if (
            not isinstance(email, str)
            or email.casefold() != self._settings.allowed_email.casefold()
        ):
            raise AccessDenied("e-posta izinli değil")
        return email


def _check_times(claims: Mapping[str, object], now: datetime) -> None:
    """PyJWT'nin kuralları: `exp`, şimdiden pay çıkarılınca bulunan andan sonra değilse süresi
    dolmuştur; `nbf` ve `iat` şimdiye pay eklenince bulunan andan sonra olamaz."""
    current = (now - _EPOCH) // _SECOND
    expires = _instant(claims.get("exp"))
    issued = _instant(claims.get("iat"))
    if expires is None or issued is None:
        raise AccessDenied("zaman alanı tamsayı değil")
    if expires <= current - LEEWAY_SECONDS:
        raise AccessDenied("süresi dolmuş")
    if issued > current + LEEWAY_SECONDS:
        raise AccessDenied("iat gelecekte")
    if "nbf" in claims:
        starts = _instant(claims["nbf"])
        if starts is None:
            raise AccessDenied("zaman alanı tamsayı değil")
        if starts > current + LEEWAY_SECONDS:
            raise AccessDenied("nbf gelecekte")


def _instant(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
