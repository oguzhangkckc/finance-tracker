import re
from datetime import time
from pathlib import Path

import pytest

from finans.domain.schedule import (
    BACKUP_AT,
    JOBS,
    MONTHLY_REPORT_AT,
    MONTHLY_REPORT_DAYS,
    PAYDAY_AT,
    SYNC_CPI_AT,
    SYNC_CPI_DAYS,
    SYNC_PRICES_AT,
    WEEKLY_REPORT_AT,
)
from finans.settings import Settings

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
UNITS = DEPLOY / "systemd"
CALENDARS = {
    "sync-prices": "Mon..Fri 21:30 Europe/Istanbul",
    "sync-cpi": "*-*-03..05 10:30 Europe/Istanbul",
    "weekly-report": "Sun 20:00 Europe/Istanbul",
    "monthly-report": "*-*-05..10 11:00 Europe/Istanbul",
    "payday": "*-*-* 09:00 Europe/Istanbul",
    "backup": "*-*-* 03:00 Europe/Istanbul",
}
TIMES: dict[str, time] = {
    "sync-prices": SYNC_PRICES_AT,
    "sync-cpi": SYNC_CPI_AT,
    "weekly-report": WEEKLY_REPORT_AT,
    "monthly-report": MONTHLY_REPORT_AT,
    "payday": PAYDAY_AT,
    "backup": BACKUP_AT,
}
SECRETS = [
    "ft_evds_api_key",
    "ft_telegram_bot_token",
    "ft_healthcheck_reports_url",
    "ft_healthcheck_backup_url",
]
HARDENING = {
    "NoNewPrivileges": "yes",
    "PrivateTmp": "yes",
    "ProtectSystem": "strict",
    "ReadWritePaths": "/var/lib/finans",
    "ProtectHome": "yes",
}


def _unit(path: Path) -> dict[str, list[tuple[str, str]]]:
    """systemd birimleri aynı anahtarı tekrar edebilir; configparser bunu kabul etmez."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections[current] = []
            continue
        key, _, value = line.partition("=")
        sections[current].append((key, value))
    return sections


def _one(entries: list[tuple[str, str]], key: str) -> str:
    [value] = [value for name, value in entries if name == key]
    return value


def test_every_job_has_a_persistent_timer_in_istanbul_time() -> None:
    timers = sorted(path.name for path in UNITS.glob("*.timer"))
    assert timers == sorted(f"finans-{job}.timer" for job in JOBS)
    for job in JOBS:
        unit = _unit(UNITS / f"finans-{job}.timer")
        assert _one(unit["Timer"], "OnCalendar") == CALENDARS[job]
        assert _one(unit["Timer"], "Persistent") == "true"
        assert _one(unit["Timer"], "Unit") == f"finans-job@{job}.service"
        assert _one(unit["Install"], "WantedBy") == "timers.target"


@pytest.mark.parametrize("job", JOBS)
def test_timer_time_matches_the_schedule_behind_logical_dates(job: str) -> None:
    clock = re.search(r"(\d\d):(\d\d) Europe/Istanbul$", CALENDARS[job])
    assert clock is not None
    assert time(int(clock[1]), int(clock[2])) == TIMES[job]


def test_timer_days_match_the_schedule() -> None:
    cpi = f"*-*-0{min(SYNC_CPI_DAYS)}..0{max(SYNC_CPI_DAYS)} "
    monthly = f"*-*-0{MONTHLY_REPORT_DAYS[0]}..{MONTHLY_REPORT_DAYS[-1]} "
    assert CALENDARS["sync-cpi"].startswith(cpi)
    assert CALENDARS["monthly-report"].startswith(monthly)


def test_service_runs_the_single_entry_point_as_its_own_user() -> None:
    service = _unit(UNITS / "finans-job@.service")["Service"]
    assert _one(service, "Type") == "oneshot"
    assert (_one(service, "User"), _one(service, "Group")) == ("finans", "finans")
    assert _one(service, "ExecStart") == "/opt/finans/.venv/bin/ft job run %i"
    assert _one(service, "EnvironmentFile") == "/etc/finans/finans.env"


def test_credentials_are_secret_settings_and_the_manual_wrapper_uses_the_same() -> None:
    service = _unit(UNITS / "finans-job@.service")["Service"]
    loaded = [value for name, value in service if name == "LoadCredential"]
    assert loaded == [f"{name}:/etc/finans/credstore/{name}" for name in SECRETS]
    for name in SECRETS:
        assert "SecretStr" in str(Settings.model_fields[name.removeprefix("ft_")].annotation)
    wrapper = (DEPLOY / "ft-finans").read_text(encoding="utf-8")
    loop = re.search(r"for name in (.+); do", wrapper)
    assert loop is not None
    assert loop[1].split() == SECRETS


def test_service_and_manual_wrapper_share_the_hardening() -> None:
    service = _unit(UNITS / "finans-job@.service")["Service"]
    wrapper = (DEPLOY / "ft-finans").read_text(encoding="utf-8")
    properties = dict(re.findall(r"-p (\w+)=(\S+)", wrapper))

    assert {name: _one(service, name) for name in HARDENING} == HARDENING
    assert {name: properties.get(name) for name in HARDENING} == HARDENING


def test_everything_the_jobs_write_is_under_the_writable_path() -> None:
    service = _unit(UNITS / "finans-job@.service")["Service"]
    writable = Path(_one(service, "ReadWritePaths"))
    example = (DEPLOY / "finans.env.example").read_text(encoding="utf-8")
    env = dict(
        line.split("=", 1)
        for line in example.splitlines()
        if "=" in line and not line.startswith("#")
    )
    wrapper = (DEPLOY / "ft-finans").read_text(encoding="utf-8")
    manual = re.search(r"--working-directory=(\S+)", wrapper)
    assert manual is not None

    written = [
        Path(env["FT_DB_PATH"]).parent,
        Path(env["FT_LOCK_DIR"]),
        Path(env["FT_BACKUP_DIR"]),
        Path(_one(service, "WorkingDirectory")),
        Path(manual[1]),
    ]
    assert all(path.is_relative_to(writable) for path in written)
    assert "FT_BACKUP_SCRATCH_DIR" not in env
    assert not Path(env["FT_PORTFOLIO_PATH"]).is_relative_to(writable)


def test_credential_files_are_read_as_settings(tmp_path: Path) -> None:
    (tmp_path / "ft_evds_api_key").write_text("deneme-anahtari", encoding="utf-8")
    (tmp_path / "ft_healthcheck_backup_url").write_text("", encoding="utf-8")

    settings = Settings(db_path=tmp_path / "finans.db", _secrets_dir=tmp_path)

    assert settings.evds_api_key is not None
    assert settings.evds_api_key.get_secret_value() == "deneme-anahtari"
    assert settings.healthcheck_backup_url is None


def test_environment_example_holds_no_secrets() -> None:
    example = (DEPLOY / "finans.env.example").read_text(encoding="utf-8")
    keys = {
        line.split("=")[0]
        for line in example.splitlines()
        if "=" in line and not line.startswith("#")
    }
    assert not keys & {name.upper() for name in SECRETS}
    assert "AGE-SECRET-KEY" not in example
