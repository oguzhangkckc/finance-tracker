"""Access JWT doğrulaması ve anahtar önbelleği (K-136): ağsız, yerel RSA anahtarıyla."""

import logging
from datetime import timedelta

import jwt
import pytest

from finans.api.auth import REFRESH_INTERVAL, AccessDenied, AccessVerifier, KeyCache
from tests.fakes.access import FakeAccessKeys
from tests.fakes.clock import FixedClock
from tests.support.access import (
    API_SETTINGS,
    EMAIL,
    KID,
    TEAM_DOMAIN,
    access_token,
    public_jwk,
    seconds,
)


def verifier_for(
    keys: FakeAccessKeys, clock: FixedClock, *, prefetch: bool = True
) -> AccessVerifier:
    cache = KeyCache(keys, clock)
    if prefetch:
        cache.prefetch()
    return AccessVerifier(API_SETTINGS, cache, clock)


def denial(verifier: AccessVerifier, token: str | None) -> str:
    with pytest.raises(AccessDenied) as caught:
        verifier.verify(token)
    return str(caught.value)


def test_a_valid_token_yields_its_email(keys: FakeAccessKeys, clock: FixedClock) -> None:
    assert verifier_for(keys, clock).verify(access_token(clock.now())) == EMAIL


@pytest.mark.parametrize("token", [None, ""])
def test_a_missing_header_is_denied(
    keys: FakeAccessKeys, clock: FixedClock, token: str | None
) -> None:
    assert denial(verifier_for(keys, clock), token) == "başlık yok"


@pytest.mark.parametrize("token", ["jeton", "a.b.c", "e30.e30.e30"])
def test_garbage_is_denied(keys: FakeAccessKeys, clock: FixedClock, token: str) -> None:
    denial(verifier_for(keys, clock), token)


def test_a_signature_from_another_key_under_the_same_kid_is_denied(
    keys: FakeAccessKeys, clock: FixedClock
) -> None:
    token = access_token(clock.now(), key="baska")
    assert denial(verifier_for(keys, clock), token) == "InvalidSignatureError"


def test_a_token_for_another_application_is_denied(keys: FakeAccessKeys, clock: FixedClock) -> None:
    token = access_token(clock.now(), aud=["baska-uygulama"])
    assert denial(verifier_for(keys, clock), token) == "InvalidAudienceError"


def test_a_token_from_another_team_is_denied(keys: FakeAccessKeys, clock: FixedClock) -> None:
    token = access_token(clock.now(), iss="https://baska.cloudflareaccess.com")
    assert denial(verifier_for(keys, clock), token) == "InvalidIssuerError"


@pytest.mark.parametrize(("offset", "valid"), [(-29, True), (-30, False), (-31, False)])
def test_expiry_has_thirty_seconds_of_leeway(
    keys: FakeAccessKeys, clock: FixedClock, offset: int, valid: bool
) -> None:
    now = clock.now()
    token = access_token(now - timedelta(hours=1), exp=seconds(now) + offset)
    verifier = verifier_for(keys, clock)
    if valid:
        assert verifier.verify(token) == EMAIL
    else:
        assert denial(verifier, token) == "süresi dolmuş"


@pytest.mark.parametrize(("offset", "valid"), [(30, True), (31, False)])
def test_not_before_in_the_future_has_thirty_seconds_of_leeway(
    keys: FakeAccessKeys, clock: FixedClock, offset: int, valid: bool
) -> None:
    token = access_token(clock.now(), nbf=seconds(clock.now()) + offset)
    verifier = verifier_for(keys, clock)
    if valid:
        assert verifier.verify(token) == EMAIL
    else:
        assert denial(verifier, token) == "nbf gelecekte"


@pytest.mark.parametrize(("offset", "valid"), [(30, True), (31, False)])
def test_issued_in_the_future_has_thirty_seconds_of_leeway(
    keys: FakeAccessKeys, clock: FixedClock, offset: int, valid: bool
) -> None:
    token = access_token(clock.now(), iat=seconds(clock.now()) + offset)
    verifier = verifier_for(keys, clock)
    if valid:
        assert verifier.verify(token) == EMAIL
    else:
        assert denial(verifier, token) == "iat gelecekte"


def test_a_token_without_not_before_is_accepted(keys: FakeAccessKeys, clock: FixedClock) -> None:
    assert verifier_for(keys, clock).verify(access_token(clock.now(), drop=("nbf",))) == EMAIL


@pytest.mark.parametrize("claim", ["exp", "iat", "aud", "iss"])
def test_a_token_without_a_required_claim_is_denied(
    keys: FakeAccessKeys, clock: FixedClock, claim: str
) -> None:
    token = access_token(clock.now(), drop=(claim,))
    assert denial(verifier_for(keys, clock), token) == "MissingRequiredClaimError"


@pytest.mark.parametrize(
    "claims", [{"exp": "2000000000"}, {"exp": True}, {"iat": "1"}, {"nbf": "1"}]
)
def test_times_that_are_not_integers_are_denied(
    keys: FakeAccessKeys, clock: FixedClock, claims: dict[str, object]
) -> None:
    denial(verifier_for(keys, clock), access_token(clock.now(), extra=claims))


@pytest.mark.parametrize(
    "claims", [{"email": "baska@example.com"}, {"email": ["kullanici@example.com"]}, {"email": ""}]
)
def test_another_account_is_denied_without_naming_it(
    keys: FakeAccessKeys, clock: FixedClock, claims: dict[str, object]
) -> None:
    reason = denial(verifier_for(keys, clock), access_token(clock.now(), extra=claims))
    assert reason == "e-posta izinli değil"


def test_a_token_without_an_email_is_denied(keys: FakeAccessKeys, clock: FixedClock) -> None:
    token = access_token(clock.now(), drop=("email",))
    assert denial(verifier_for(keys, clock), token) == "e-posta izinli değil"


def test_the_email_is_compared_without_case(keys: FakeAccessKeys, clock: FixedClock) -> None:
    token = access_token(clock.now(), email="Kullanici@Example.COM")
    assert verifier_for(keys, clock).verify(token) == "Kullanici@Example.COM"


def test_a_token_signed_with_another_algorithm_is_denied(
    keys: FakeAccessKeys, clock: FixedClock
) -> None:
    payload = jwt.decode(access_token(clock.now()), options={"verify_signature": False})
    hmac_token = jwt.encode(payload, "x" * 32, algorithm="HS256", headers={"kid": KID})
    unsigned = jwt.encode(payload, "", algorithm="none", headers={"kid": KID})
    verifier = verifier_for(keys, clock)
    assert denial(verifier, hmac_token) == "beklenmeyen imza algoritması"
    assert denial(verifier, unsigned) == "beklenmeyen imza algoritması"


def test_a_token_without_a_key_id_is_denied(keys: FakeAccessKeys, clock: FixedClock) -> None:
    assert denial(verifier_for(keys, clock), access_token(clock.now(), kid=None)) == (
        "anahtar kimliği yok"
    )


def test_reasons_never_hold_the_token(keys: FakeAccessKeys, clock: FixedClock) -> None:
    token = access_token(clock.now(), key="baska")
    assert token not in denial(verifier_for(keys, clock), token)


def test_an_unknown_kid_refreshes_once_and_a_rotated_key_is_accepted(
    keys: FakeAccessKeys, clock: FixedClock
) -> None:
    verifier = verifier_for(keys, clock)
    keys.keys = [public_jwk("yeni", kid="anahtar-2")]
    clock.advance(REFRESH_INTERVAL)

    assert verifier.verify(access_token(clock.now(), key="yeni", kid="anahtar-2")) == EMAIL
    assert keys.calls == 2


def test_an_unknown_kid_refreshes_at_most_every_five_minutes(
    keys: FakeAccessKeys, clock: FixedClock
) -> None:
    verifier = verifier_for(keys, clock)
    clock.advance(REFRESH_INTERVAL)
    stranger = access_token(clock.now(), key="baska", kid="yabanci")

    assert denial(verifier, stranger) == "anahtar bulunamadı"
    assert keys.calls == 2
    clock.advance(REFRESH_INTERVAL - timedelta(seconds=1))
    denial(verifier, stranger)
    assert keys.calls == 2
    clock.advance(timedelta(seconds=1))
    denial(verifier, stranger)
    assert keys.calls == 3


def test_a_known_kid_never_refreshes(keys: FakeAccessKeys, clock: FixedClock) -> None:
    verifier = verifier_for(keys, clock)
    clock.advance(REFRESH_INTERVAL * 3)
    verifier.verify(access_token(clock.now()))
    assert keys.calls == 1


def test_with_the_key_server_down_and_an_empty_cache_requests_are_denied(
    clock: FixedClock,
) -> None:
    keys = FakeAccessKeys([public_jwk()], down=True)
    verifier = verifier_for(keys, clock)

    assert denial(verifier, access_token(clock.now())) == "anahtar bulunamadı"
    clock.advance(REFRESH_INTERVAL)
    assert denial(verifier, access_token(clock.now())) == "anahtar bulunamadı"
    assert keys.calls == 2


def test_with_the_key_server_down_a_cached_key_is_still_accepted(
    keys: FakeAccessKeys, clock: FixedClock
) -> None:
    verifier = verifier_for(keys, clock)
    keys.down = True
    clock.advance(REFRESH_INTERVAL * 2)

    assert verifier.verify(access_token(clock.now())) == EMAIL


def test_a_failed_refresh_keeps_the_cached_keys(keys: FakeAccessKeys, clock: FixedClock) -> None:
    verifier = verifier_for(keys, clock)
    keys.down = True
    clock.advance(REFRESH_INTERVAL)

    denial(verifier, access_token(clock.now(), key="yeni", kid="anahtar-2"))
    assert keys.calls == 2
    assert verifier.verify(access_token(clock.now())) == EMAIL


def test_a_failed_prefetch_starts_the_service_and_it_recovers_on_a_later_refresh(
    clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    keys = FakeAccessKeys([public_jwk()], down=True)
    with caplog.at_level(logging.WARNING, logger="finans.api"):
        verifier = verifier_for(keys, clock)

    assert [r.getMessage() for r in caplog.records] == [
        "Access anahtarları alınamadı: ConnectError"
    ]
    denial(verifier, access_token(clock.now()))
    keys.down = False
    clock.advance(REFRESH_INTERVAL)
    assert verifier.verify(access_token(clock.now())) == EMAIL


def test_without_a_prefetch_the_first_request_fetches(
    keys: FakeAccessKeys, clock: FixedClock
) -> None:
    verifier = verifier_for(keys, clock, prefetch=False)
    assert verifier.verify(access_token(clock.now())) == EMAIL
    assert keys.calls == 1


def test_keys_that_cannot_verify_rs256_are_skipped(clock: FixedClock) -> None:
    good = public_jwk()
    keys = FakeAccessKeys(
        [
            {**public_jwk("ikinci", kid="sifreleme"), "use": "enc"},
            {**public_jwk("ucuncu", kid="rs512"), "alg": "RS512"},
            {**public_jwk("dorduncu", kid="bozuk"), "n": "!!!"},
            {key: value for key, value in public_jwk("besinci").items() if key != "kid"},
            {"kty": "EC", "kid": "eliptik", "crv": "P-256", "x": "AA", "y": "AA"},
            {"kty": "oct", "kid": "simetrik", "k": "AAAA"},
            good,
        ]
    )
    verifier = verifier_for(keys, clock)

    assert verifier.verify(access_token(clock.now())) == EMAIL
    for kid, name in [("sifreleme", "ikinci"), ("rs512", "ucuncu"), ("bozuk", "dorduncu")]:
        assert denial(verifier, access_token(clock.now(), key=name, kid=kid)) == (
            "anahtar bulunamadı"
        )


def test_a_key_list_with_nothing_usable_keeps_the_cached_keys(
    keys: FakeAccessKeys, clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    verifier = verifier_for(keys, clock)
    keys.keys = [{"kty": "oct", "kid": "simetrik", "k": "AAAA"}]
    clock.advance(REFRESH_INTERVAL)

    with caplog.at_level(logging.WARNING, logger="finans.api"):
        denial(verifier, access_token(clock.now(), key="baska", kid="simetrik"))
    assert [r.getMessage() for r in caplog.records] == [
        "Access anahtar listesinde kullanılabilir RS256 anahtarı yok"
    ]
    assert verifier.verify(access_token(clock.now())) == EMAIL


def test_the_issuer_is_the_team_address() -> None:
    assert API_SETTINGS.issuer == f"https://{TEAM_DOMAIN}"
