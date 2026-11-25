"""Yazma şifresinin scrypt özeti; şifre ekrana, log'a ve dosyaya yazılmaz (K-105, K-126)."""

import base64
import hashlib
import hmac
import secrets
from typing import Final

SCRYPT_N: Final = 2**15
SCRYPT_R: Final = 8
SCRYPT_P: Final = 1
# 128·n·r = 32 MiB; hashlib'in varsayılan sınırı (32 MiB) bunu kabul etmez.
SCRYPT_MAXMEM: Final = 64 * 1024 * 1024
MIN_LENGTH: Final = 12
_MAX_N: Final = 2**17
_SALT_BYTES: Final = 16
_DIGEST_BYTES: Final = 32


class PasswordError(ValueError):
    pass


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=_DIGEST_BYTES
    )


def check_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordError(
            f"Şifre en az {MIN_LENGTH} karakter olmalı; {len(password)} verildi. Kısa şifre "
            "denemeyle bulunabilir; birkaç kelimelik bir parola cümlesi hem uzun hem kolay "
            "hatırlanır."
        )


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    check_password(password)
    salt = secrets.token_bytes(_SALT_BYTES) if salt is None else salt
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_encode(salt)}${_encode(digest)}"


def _parse(stored: str) -> tuple[int, bytes, bytes] | None:
    parts = stored.strip().split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = (int(part) for part in parts[1:4])
        salt, expected = _decode(parts[4]), _decode(parts[5])
    except ValueError:
        return None
    if not (2 <= n <= _MAX_N and r == SCRYPT_R and p == SCRYPT_P) or len(expected) != _DIGEST_BYTES:
        return None
    return n, salt, expected


def well_formed(stored: str) -> bool:
    return _parse(stored) is not None


def verify_password(password: str, stored: str) -> bool:
    """Bozuk ya da aşırı pahalı bir özet doğrulamaz; karşılaştırma sabit zamanlı."""
    parsed = _parse(stored)
    if parsed is None:
        return False
    n, salt, expected = parsed
    return hmac.compare_digest(_scrypt(password, salt, n, SCRYPT_R, SCRYPT_P), expected)
