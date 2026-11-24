from pathlib import Path

import pytest
from pydantic import ValidationError

from finans.settings import load_settings


def test_reads_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    settings = load_settings()
    assert settings.db_path == tmp_path / "finans.db"
    assert settings.portfolio_path is None
    assert settings.log_level == "INFO"


def test_db_path_is_required() -> None:
    with pytest.raises(ValidationError, match="db_path"):
        load_settings()


def test_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValidationError, match="log_level"):
        load_settings()


def test_reads_dotenv_in_working_directory_and_ignores_unrelated_keys(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FT_DB_PATH=var/dev.db\nUNRELATED=1\n", encoding="utf-8")
    assert load_settings().db_path == Path("var/dev.db")


def test_reads_systemd_credentials_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "FT_LOG_LEVEL").write_text("DEBUG", encoding="utf-8")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    assert load_settings().log_level == "DEBUG"


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    settings = load_settings()
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]


def test_evds_settings_have_defaults_and_the_key_stays_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    assert load_settings().evds_api_key is None

    monkeypatch.setenv("FT_EVDS_API_KEY", "gizli-deger")
    settings = load_settings()
    assert settings.evds_api_key is not None
    assert settings.evds_api_key.get_secret_value() == "gizli-deger"
    assert "gizli-deger" not in repr(settings)
    assert settings.evds_base_url == "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
    assert (settings.cpi_series, settings.cpi_base) == ("TP.TUKFIY2025.GENEL", "2025=100")


def test_empty_evds_key_counts_as_undefined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_EVDS_API_KEY", "  ")
    assert load_settings().evds_api_key is None


def test_tefas_settings_default_to_a_polite_interval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    settings = load_settings()
    assert settings.tefas_base_url == "https://www.tefas.gov.tr/api/funds/"
    assert settings.tefas_min_interval_s == 10

    monkeypatch.setenv("FT_TEFAS_MIN_INTERVAL_S", "3")
    with pytest.raises(ValidationError, match="tefas_min_interval_s"):
        load_settings()
