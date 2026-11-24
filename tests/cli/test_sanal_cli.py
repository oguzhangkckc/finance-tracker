import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.adapters.sqlite.connection import is_sanal
from finans.cli.main import app

runner = CliRunner()
PORTFOLIO = """
[targets]
hisse = 1

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse"
"""


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def real_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(portfolio))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    return tmp_path / "finans.db"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sanal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FT_PROFILE", "sanal")


def test_init_creates_a_marked_database_next_to_the_real_one_without_touching_it(
    monkeypatch: pytest.MonkeyPatch, real_db: Path
) -> None:
    before = _digest(real_db)
    _sanal(monkeypatch)

    result = runner.invoke(app, ["sanal", "init"])

    assert result.exit_code == 0, result.output
    sanal_db = real_db.parent / "sanal.db"
    assert f"Sanal veritabanı kuruldu: {sanal_db}" in result.output
    assert is_sanal(sanal_db)
    assert _digest(real_db) == before
    listed = runner.invoke(app, ["tx", "list"])
    assert listed.exit_code == 0, listed.output
    assert "Kayıtlı işlem yok." in listed.output


def test_init_refuses_an_existing_file(monkeypatch: pytest.MonkeyPatch, real_db: Path) -> None:
    _sanal(monkeypatch)
    assert runner.invoke(app, ["sanal", "init"]).exit_code == 0

    again = runner.invoke(app, ["sanal", "init"])

    assert again.exit_code == 1
    assert "zaten var" in again.output


@pytest.mark.parametrize(
    "command",
    [["sanal", "init"], ["sanal", "reset", "--evet"]],
)
def test_sanal_commands_need_the_sanal_profile(real_db: Path, command: list[str]) -> None:
    result = runner.invoke(app, command)

    assert result.exit_code == 1
    assert "yalnızca sanal profilde" in result.output
    assert not (real_db.parent / "sanal.db").exists()


@pytest.mark.parametrize(
    "command",
    [
        ["value"],
        ["tx", "list"],
        ["tx", "add", "buy", "XHT", "1", "10", "--date", "2026-06-15"],
        ["report", "weekly", "--on", "2026-11-29"],
        ["alerts"],
        ["db", "migrate"],
        ["job", "run", "weekly-report", "--logical-date", "2026-11-29"],
    ],
)
def test_real_profile_refuses_a_sanal_database_in_every_command(
    monkeypatch: pytest.MonkeyPatch, real_db: Path, command: list[str]
) -> None:
    monkeypatch.setenv("FT_PROFILE", "sanal")
    assert runner.invoke(app, ["sanal", "init"]).exit_code == 0
    monkeypatch.delenv("FT_PROFILE")
    sanal_db = real_db.parent / "sanal.db"
    monkeypatch.setenv("FT_DB_PATH", str(sanal_db))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(real_db.parent / "baska.db"))
    before = _digest(sanal_db)

    result = runner.invoke(app, command)

    assert result.exit_code == 1, result.output
    assert "sanal portföye ait" in result.output
    assert _digest(sanal_db) == before


@pytest.mark.parametrize(
    "command",
    [
        ["tx", "list"],
        ["tx", "add", "buy", "XHT", "1", "10", "--date", "2026-06-15"],
        ["db", "migrate"],
    ],
)
def test_sanal_profile_refuses_an_unmarked_database(
    monkeypatch: pytest.MonkeyPatch, real_db: Path, command: list[str]
) -> None:
    before = _digest(real_db)
    _sanal(monkeypatch)
    monkeypatch.setenv("FT_DB_PATH", str(real_db.parent / "gercek-baska.db"))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(real_db))

    result = runner.invoke(app, command)

    assert result.exit_code == 1, result.output
    assert "sanal değil" in result.output
    assert _digest(real_db) == before


def test_sanal_profile_without_init_creates_nothing(
    monkeypatch: pytest.MonkeyPatch, real_db: Path
) -> None:
    _sanal(monkeypatch)

    for command in (["tx", "list"], ["db", "migrate"], ["config", "apply"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 1, result.output
        assert "ft sanal init" in result.output
    assert not (real_db.parent / "sanal.db").exists()


def test_doctor_reports_a_profile_mismatch_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, real_db: Path
) -> None:
    _sanal(monkeypatch)
    monkeypatch.setenv("FT_DB_PATH", str(real_db.parent / "gercek-baska.db"))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(real_db))

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "✗ Veritabanı profili: Bu veritabanı sanal değil" in result.output


def test_reset_needs_confirmation_and_deletes_only_the_marked_file(
    monkeypatch: pytest.MonkeyPatch, real_db: Path
) -> None:
    _sanal(monkeypatch)
    assert runner.invoke(app, ["sanal", "init"]).exit_code == 0
    sanal_db = real_db.parent / "sanal.db"

    unconfirmed = runner.invoke(app, ["sanal", "reset"])
    assert unconfirmed.exit_code == 2
    assert "--evet" in unconfirmed.output
    assert sanal_db.exists()

    confirmed = runner.invoke(app, ["sanal", "reset", "--evet"])
    assert confirmed.exit_code == 0, confirmed.output
    assert f"Silindi: {sanal_db}" in confirmed.output
    assert not sanal_db.exists()
    assert real_db.exists()


def test_reset_refuses_an_unmarked_file(monkeypatch: pytest.MonkeyPatch, real_db: Path) -> None:
    before = _digest(real_db)
    _sanal(monkeypatch)
    monkeypatch.setenv("FT_DB_PATH", str(real_db.parent / "gercek-baska.db"))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(real_db))

    result = runner.invoke(app, ["sanal", "reset", "--evet"])

    assert result.exit_code == 1
    assert "sanal olarak işaretli değil" in result.output
    assert _digest(real_db) == before


def test_same_path_is_a_settings_error_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, real_db: Path
) -> None:
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(real_db))

    result = runner.invoke(app, ["tx", "list"])

    assert result.exit_code == 2
    assert "Ayar hatası: Sanal veritabanı gerçek veritabanıyla aynı dosya olamaz" in result.output
