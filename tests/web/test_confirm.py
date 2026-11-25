"""Onay formu imzası: oturuma bağlı, 10 dakika geçerli, tek kullanımlık nonce (K-126)."""

from datetime import UTC, datetime, timedelta

import pytest

from finans.web.confirm import NONCE_FIELD, SIGNATURE_FIELD, sign, verify

KEY = b"k" * 64
NOW = datetime(2026, 12, 15, 9, 0, tzinfo=UTC)
FIELDS = {"profil": "real", "islem": "alis", "fon": "XHT", "adet": "573", "sonuc": "abc"}


def test_a_signed_form_verifies_in_the_same_session_and_returns_its_fields() -> None:
    form = sign(KEY, "oturum", FIELDS, now=NOW)

    result = verify(KEY, "oturum", form, now=NOW + timedelta(minutes=9, seconds=59))

    assert result.status == "ok"
    assert {k: result.fields[k] for k in FIELDS} == FIELDS
    assert 16 <= len(result.nonce) <= 64
    assert sign(KEY, "oturum", FIELDS, now=NOW)[NONCE_FIELD] != form[NONCE_FIELD]


@pytest.mark.parametrize(
    ("change", "session"),
    [
        ({"adet": "574"}, "oturum"),
        ({"sonuc": "def"}, "oturum"),
        ({"profil": "sanal"}, "oturum"),
        ({"fazladan": "1"}, "oturum"),
        ({SIGNATURE_FIELD: "0" * 64}, "oturum"),
        ({SIGNATURE_FIELD: "ğ"}, "oturum"),
        ({}, "baska-oturum"),
    ],
)
def test_a_changed_field_or_another_session_is_refused(
    change: dict[str, str], session: str
) -> None:
    form = {**sign(KEY, "oturum", FIELDS, now=NOW), **change}

    assert verify(KEY, session, form, now=NOW).status == "invalid"


def test_a_missing_signature_is_refused() -> None:
    form = sign(KEY, "oturum", FIELDS, now=NOW)
    del form[SIGNATURE_FIELD]

    assert verify(KEY, "oturum", form, now=NOW).status == "invalid"


@pytest.mark.parametrize("delta", [timedelta(minutes=10, seconds=1), timedelta(minutes=-2)])
def test_a_form_older_than_ten_minutes_or_from_the_future_has_expired(delta: timedelta) -> None:
    form = sign(KEY, "oturum", FIELDS, now=NOW)

    assert verify(KEY, "oturum", form, now=NOW + delta).status == "expired"
