"""Yazma şifresinin scrypt özeti (K-105, K-126)."""

import hashlib

import pytest

from finans.application.password import (
    MIN_LENGTH,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
    PasswordError,
    hash_password,
    verify_password,
    well_formed,
)

GOOD = "uzun bir parola cümlesi"
STORED = hash_password(GOOD, salt=b"\x01" * 16)


def test_the_hash_records_its_parameters_and_verifies_only_the_right_password() -> None:
    algorithm, n, r, p, salt, digest = STORED.split("$")

    assert (algorithm, n, r, p) == ("scrypt", "32768", "8", "1")
    assert salt == "AQEBAQEBAQEBAQEBAQEBAQ"
    assert len(digest) == 43
    assert verify_password(GOOD, STORED)
    assert not verify_password(GOOD + " ", STORED)
    assert GOOD not in STORED


def test_two_hashes_of_the_same_password_differ_by_their_salt() -> None:
    assert hash_password(GOOD) != hash_password(GOOD)


@pytest.mark.parametrize("short", ["", "a" * (MIN_LENGTH - 1)])
def test_a_password_shorter_than_twelve_characters_is_refused_with_the_reason(short: str) -> None:
    with pytest.raises(PasswordError, match="en az 12 karakter"):
        hash_password(short)


@pytest.mark.parametrize(
    "broken",
    [
        "",
        "scrypt$32768$8$1$tuz",
        "bcrypt$1$2$3$AQ$AQ",
        "scrypt$x$8$1$AQ$AQ",
        "scrypt$4194304$8$1$AQ$AQ",
    ],
)
def test_an_unreadable_or_too_costly_hash_never_verifies(broken: str) -> None:
    assert not well_formed(broken)
    assert not verify_password(GOOD, broken)


def test_a_trailing_newline_from_tee_is_harmless() -> None:
    assert well_formed(STORED + "\n")
    assert verify_password(GOOD, STORED + "\n")


def test_these_parameters_need_an_explicit_memory_limit() -> None:
    # 128·n·r = 32 MiB, hashlib'in varsayılan sınırını aşar; maxmem açıkça verilmeli.
    with pytest.raises(ValueError, match="memory limit exceeded"):
        hashlib.scrypt(b"x", salt=b"s" * 16, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
