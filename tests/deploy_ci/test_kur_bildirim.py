"""Deploy bildirimi (K-135): Telegram'a `curl -K -` ile; token komut satırına, log'a, sonuç
dosyasına ve CI günlüğüne girmez. Bildirim gitmese de deploy sonucu değişmez. `curl` sahtedir."""

import json
import os
from datetime import date
from pathlib import Path

import pytest

import kur
from tests.deploy_ci.conftest import LOGIN, Pi, Systemd

TOKEN = "1234567890:AAH" + "x" * 32
CHAT = "-1001234567"
SHA = "0123456789abcdef0123456789abcdef01234567"
IDENT = "d" * 32
FAKE_CURL = """#!/bin/sh
cat > "$FAKE_CURL_CONFIG"
printf '%s\\n' "$*" > "$FAKE_CURL_ARGS"
if [ -n "$FAKE_CURL_STDERR" ]; then printf '%s\\n' "$FAKE_CURL_STDERR" >&2; fi
exit "${FAKE_CURL_EXIT:-0}"
"""


@pytest.fixture
def curl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sahte curl: standart girdiyi (yapılandırma) ve argümanları dosyaya yazar."""
    bin_dir = tmp_path / "curl-bin"
    bin_dir.mkdir()
    executable = bin_dir / "curl"
    executable.write_text(FAKE_CURL, encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CURL_CONFIG", str(tmp_path / "curl.config"))
    monkeypatch.setenv("FAKE_CURL_ARGS", str(tmp_path / "curl.args"))
    monkeypatch.delenv("FAKE_CURL_EXIT", raising=False)
    monkeypatch.delenv("FAKE_CURL_STDERR", raising=False)
    return tmp_path


@pytest.fixture
def credentials(tmp_path: Path) -> dict[str, str]:
    directory = tmp_path / "credentials"
    directory.mkdir()
    (directory / kur.TELEGRAM_CREDENTIAL).write_text(f"{TOKEN}\n", encoding="utf-8")
    return {"CREDENTIALS_DIRECTORY": str(directory), "FT_TELEGRAM_CHAT_ID": CHAT}


def test_the_token_comes_from_the_credential_and_the_chat_from_the_settings(
    credentials: dict[str, str],
) -> None:
    assert kur.telegram_from(credentials) == kur.Telegram(TOKEN, CHAT)


@pytest.mark.parametrize(
    "change",
    [
        {"CREDENTIALS_DIRECTORY": ""},
        {"FT_TELEGRAM_CHAT_ID": ""},
        {"FT_TELEGRAM_CHAT_ID": "@kanal"},
        {"FT_TELEGRAM_CHAT_ID": "123\nurl=x"},
    ],
)
def test_without_a_usable_token_or_chat_nothing_is_sent(
    credentials: dict[str, str], change: dict[str, str]
) -> None:
    assert kur.telegram_from({**credentials, **change}) is None


@pytest.mark.parametrize("token", ["", "token", "123:kısa", f'{TOKEN}"\nurl = "https://x'])
def test_a_malformed_token_is_not_used(credentials: dict[str, str], token: str) -> None:
    path = Path(credentials["CREDENTIALS_DIRECTORY"]) / kur.TELEGRAM_CREDENTIAL
    path.write_text(token, encoding="utf-8")

    assert kur.telegram_from(credentials) is None


def test_a_missing_credential_file_is_not_used(credentials: dict[str, str]) -> None:
    (Path(credentials["CREDENTIALS_DIRECTORY"]) / kur.TELEGRAM_CREDENTIAL).unlink()

    assert kur.telegram_from(credentials) is None


def test_the_curl_config_escapes_the_text_and_allows_only_https() -> None:
    text = 'tırnak " ters \\ eğik\nyeni satır\tsekme'

    config = kur.curl_config(kur.Telegram(TOKEN, CHAT), text)

    assert config.splitlines() == [
        f'url = "https://api.telegram.org/bot{TOKEN}/sendMessage"',
        f'data-urlencode = "chat_id={CHAT}"',
        'data-urlencode = "text=tırnak \\" ters \\\\ eğik\\nyeni satır\\tsekme"',
        'proto = "=https"',
        "max-time = 20",
        "fail",
        "silent",
        "show-error",
    ]


def test_a_long_text_is_cut_to_telegrams_limit() -> None:
    config = kur.curl_config(kur.Telegram(TOKEN, CHAT), "a" * 5000)

    assert f'"text={"a" * kur.TELEGRAM_LIMIT}"' in config


def test_the_token_goes_through_standard_input_never_the_command_line(curl: Path) -> None:
    telegram = kur.Telegram(TOKEN, CHAT)

    problem = kur.send_telegram(telegram, "✅ finans güncellendi")

    assert problem is None
    assert (curl / "curl.args").read_text(encoding="utf-8") == "-K -\n"
    assert (curl / "curl.config").read_text(encoding="utf-8") == kur.curl_config(
        telegram, "✅ finans güncellendi"
    )


def test_a_failed_send_is_reported_without_the_token(
    curl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CURL_EXIT", "22")
    monkeypatch.setenv(
        "FAKE_CURL_STDERR", f"curl: (22) https://api.telegram.org/bot{TOKEN}/sendMessage: 401"
    )

    problem = kur.send_telegram(kur.Telegram(TOKEN, CHAT), "deneme")

    assert problem == (
        "Telegram bildirimi gönderilemedi (curl 22): "
        "curl: (22) https://api.telegram.org/bot***/sendMessage: 401"
    )


def test_secrets_and_anything_shaped_like_a_token_are_scrubbed() -> None:
    text = f"hata: {TOKEN} ve 9876543210:{'B' * 35} gizli-deger; commit {SHA}"

    assert kur.scrub(text, ["gizli-deger"]) == f"hata: *** ve *** ***; commit {SHA}"


def _env(systemd: Systemd) -> kur.Ortam:
    return kur.Ortam(kur.run, systemd.sleep, systemd.now, date(2026, 12, 16), LOGIN)


def _request(pi: Pi) -> None:
    pi.paths.istek.write_text(f"{SHA}\n{IDENT}\n", encoding="ascii")


def test_main_scrubs_the_result_before_writing_it_and_sending_it(
    pi: Pi,
    systemd: Systemd,
    curl: Path,
    credentials: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    leaked = kur.Sonuc(kur.Kod.BASARISIZ, f"❌ başarısız: uv: bot{TOKEN} reddedildi.", SHA)
    monkeypatch.setattr(kur, "deploy", lambda _paths, _sha, _env: leaked)
    _request(pi)

    code = kur.main(pi.paths, _env(systemd), environ=credentials)

    written = (pi.paths.sonuc / f"{IDENT}.json").read_text(encoding="utf-8")
    sent = (curl / "curl.config").read_text(encoding="utf-8")
    assert code == kur.Kod.BASARISIZ
    assert TOKEN not in written
    assert json.loads(written)["mesaj"] == "❌ başarısız: uv: bot*** reddedildi."
    assert 'data-urlencode = "text=❌ başarısız: uv: bot*** reddedildi."' in sent
    assert TOKEN not in capsys.readouterr().err


def test_already_installed_and_busy_results_are_not_sent(
    pi: Pi, systemd: Systemd, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    def notify(text: str) -> str | None:
        sent.append(text)
        return None

    for quiet in (
        kur.Sonuc(kur.Kod.TAMAM, "0123456 zaten kurulu; bir şey yapılmadı.", SHA, bildir=False),
        kur.Sonuc(kur.Kod.MESGUL, "⏳ Pencere dışı", SHA, bildir=False),
    ):
        monkeypatch.setattr(kur, "deploy", lambda _p, _s, _e, result=quiet: result)
        _request(pi)
        kur.main(pi.paths, _env(systemd), notify, environ={})

    assert sent == []


def test_a_notification_that_fails_does_not_change_the_result(
    pi: Pi,
    systemd: Systemd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    done = kur.Sonuc(kur.Kod.TAMAM, "✅ finans güncellendi: 0123456", SHA)
    monkeypatch.setattr(kur, "deploy", lambda _paths, _sha, _env: done)
    _request(pi)

    code = kur.main(pi.paths, _env(systemd), environ={})

    assert code == kur.Kod.TAMAM
    assert capsys.readouterr().err.splitlines() == [
        "✅ finans güncellendi: 0123456",
        kur.NO_TELEGRAM,
    ]
