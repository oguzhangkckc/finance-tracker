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


def test_real_profile_is_the_default_and_keeps_its_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(tmp_path / "portfolio.toml"))
    settings = load_settings()

    assert settings.profile == "real"
    assert settings.db_path == tmp_path / "finans.db"
    assert settings.lock_dir is None


def test_sanal_profile_uses_its_own_database_and_locks_but_the_same_portfolio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(tmp_path / "portfolio.toml"))
    monkeypatch.setenv("FT_PROFILE", "sanal")
    settings = load_settings()

    assert settings.db_path == tmp_path / "sanal.db"
    assert settings.portfolio_path == tmp_path / "portfolio.toml"
    assert settings.lock_dir == tmp_path / "locks" / "sanal"


def test_sanal_paths_can_be_set_explicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PROFILE", "sanal")
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(tmp_path / "deneme" / "s.db"))
    monkeypatch.setenv("FT_SANAL_PORTFOLIO_PATH", str(tmp_path / "s.toml"))
    monkeypatch.setenv("FT_LOCK_DIR", str(tmp_path / "kilitler"))
    settings = load_settings()

    assert settings.db_path == tmp_path / "deneme" / "s.db"
    assert settings.portfolio_path == tmp_path / "s.toml"
    assert settings.lock_dir == tmp_path / "kilitler" / "sanal"


def test_sanal_database_cannot_be_the_real_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(tmp_path / "finans.db"))
    with pytest.raises(ValidationError, match="aynı dosya olamaz"):
        load_settings()


def test_migration_copies_live_beside_each_profiles_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(tmp_path / "sanal" / "sanal.db"))
    monkeypatch.setenv("FT_BACKUP_DIR", str(tmp_path / "backups"))

    assert load_settings().migration_backup_dir == tmp_path / "migration-backups"
    monkeypatch.setenv("FT_PROFILE", "sanal")
    assert load_settings().migration_backup_dir == tmp_path / "sanal" / "migration-backups"


@pytest.mark.parametrize(
    "backup_dir",
    [
        "migration-backups",
        "migration-backups/yedek",
        ".",
        "sanal/migration-backups",
        "sanal",
    ],
)
def test_nightly_backups_cannot_mix_with_migration_copies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backup_dir: str
) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_SANAL_DB_PATH", str(tmp_path / "sanal" / "sanal.db"))
    monkeypatch.setenv("FT_BACKUP_DIR", str(tmp_path / backup_dir))
    with pytest.raises(ValidationError, match=r"FT_BACKUP_DIR .*\(K-142\)"):
        load_settings()


@pytest.mark.parametrize("source", ["ortam", ".env"])
def test_leftover_w2_web_settings_do_not_stop_the_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str
) -> None:
    """K-136: FT_WEB_ALLOWED_LOGIN geçiş gününde finans.env'den (Pi) ya da .env'den (yerel)
    silinene kadar durabilir."""
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    if source == "ortam":
        monkeypatch.setenv("FT_WEB_ALLOWED_LOGIN", "kisi@example.com")
    else:
        (tmp_path / ".env").write_text("FT_WEB_ALLOWED_LOGIN=kisi@example.com\n", encoding="utf-8")

    settings = load_settings()

    assert settings.db_path == tmp_path / "finans.db"
    assert not hasattr(settings, "web_allowed_login")


def test_unknown_profile_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PROFILE", "demo")
    with pytest.raises(ValidationError, match="profile"):
        load_settings()
