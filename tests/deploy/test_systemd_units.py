import re
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Literal

import pytest

from finans import bootstrap
from finans.adapters.refresh_request import FileRefreshRequests
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.schedule import (
    BACKUP_AT,
    JOBS,
    MONTHLY_REPORT_AT,
    MONTHLY_REPORT_DAYS,
    PAYDAY_AT,
    SYNC_CPI_AT,
    SYNC_CPI_DAYS,
    SYNC_PRICES_TIMES,
    WEEKLY_REPORT_AT,
)
from finans.settings import Settings, resolve_profile

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
UNITS = DEPLOY / "systemd"
CALENDARS: dict[str, tuple[str, ...]] = {
    "sync-prices": ("Mon..Fri 12:00 Europe/Istanbul", "Mon..Fri 21:30 Europe/Istanbul"),
    "sync-cpi": ("*-*-03..05 10:30 Europe/Istanbul",),
    "weekly-report": ("Sun 20:00 Europe/Istanbul",),
    "monthly-report": ("*-*-05..10 11:00 Europe/Istanbul",),
    "payday": ("*-*-* 09:00 Europe/Istanbul",),
    "backup": ("*-*-* 03:00 Europe/Istanbul",),
}
TIMES: dict[str, tuple[time, ...]] = {
    "sync-prices": SYNC_PRICES_TIMES,
    "sync-cpi": (SYNC_CPI_AT,),
    "weekly-report": (WEEKLY_REPORT_AT,),
    "monthly-report": (MONTHLY_REPORT_AT,),
    "payday": (PAYDAY_AT,),
    "backup": (BACKUP_AT,),
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


def _calendars(entries: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(value for name, value in entries if name == "OnCalendar")


def _env() -> dict[str, str]:
    example = (DEPLOY / "finans.env.example").read_text(encoding="utf-8")
    return dict(
        line.split("=", 1)
        for line in example.splitlines()
        if "=" in line and not line.startswith("#")
    )


def test_every_job_has_a_persistent_timer_in_istanbul_time() -> None:
    timers = sorted(
        path.name for path in UNITS.glob("*.timer") if not path.name.startswith("finans-sanal-")
    )
    assert timers == sorted(f"finans-{job}.timer" for job in JOBS)
    for job in JOBS:
        unit = _unit(UNITS / f"finans-{job}.timer")
        assert _calendars(unit["Timer"]) == CALENDARS[job]
        assert _one(unit["Timer"], "Persistent") == "true"
        assert _one(unit["Timer"], "Unit") == f"finans-job@{job}.service"
        assert _one(unit["Install"], "WantedBy") == "timers.target"


@pytest.mark.parametrize("job", JOBS)
def test_timer_time_matches_the_schedule_behind_logical_dates(job: str) -> None:
    clocks = [re.search(r"(\d\d):(\d\d) Europe/Istanbul$", c) for c in CALENDARS[job]]
    assert all(clocks)
    assert tuple(time(int(c[1]), int(c[2])) for c in clocks if c) == TIMES[job]


def test_timer_days_match_the_schedule() -> None:
    cpi = f"*-*-0{min(SYNC_CPI_DAYS)}..0{max(SYNC_CPI_DAYS)} "
    monthly = f"*-*-0{MONTHLY_REPORT_DAYS[0]}..{MONTHLY_REPORT_DAYS[-1]} "
    assert CALENDARS["sync-cpi"][0].startswith(cpi)
    assert CALENDARS["monthly-report"][0].startswith(monthly)


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
    (tmp_path / "ft_web_password").write_text("\n", encoding="utf-8")

    settings = Settings(db_path=tmp_path / "finans.db", _secrets_dir=tmp_path)

    assert settings.evds_api_key is not None
    assert settings.evds_api_key.get_secret_value() == "deneme-anahtari"
    assert settings.healthcheck_backup_url is None
    assert settings.web_password is None


def test_environment_example_holds_no_secrets() -> None:
    example = (DEPLOY / "finans.env.example").read_text(encoding="utf-8")
    keys = {
        line.split("=")[0]
        for line in example.splitlines()
        if "=" in line and not line.startswith("#")
    }
    assert not keys & {name.upper() for name in SECRETS}
    assert "AGE-SECRET-KEY" not in example
    # K-107: profil ortak ayar dosyasında seçilmez; sanal işler kendi birimlerinde seçer.
    assert "FT_PROFILE" not in keys


SANAL_JOBS = ("sync-prices", "sync-cpi", "weekly-report", "monthly-report", "payday", "backup")
SANAL_SECRETS = ["ft_evds_api_key", "ft_telegram_bot_token"]


def test_sanal_timers_follow_the_real_calendar_and_run_after_the_real_jobs() -> None:
    timers = sorted(path.name for path in UNITS.glob("finans-sanal-*.timer"))
    assert timers == sorted(f"finans-sanal-{job}.timer" for job in SANAL_JOBS)
    # K-121, K-122: sanal fiyat senkronu gerçeğinden sonra; istekler üst üste binmez.
    calendars = {
        **CALENDARS,
        "sync-prices": ("Mon..Fri 12:15 Europe/Istanbul", "Mon..Fri 21:45 Europe/Istanbul"),
        "backup": ("*-*-* 03:15 Europe/Istanbul",),
    }
    for job in SANAL_JOBS:
        unit = _unit(UNITS / f"finans-sanal-{job}.timer")
        assert _calendars(unit["Timer"]) == calendars[job]
        assert _one(unit["Timer"], "Persistent") == "true"
        assert _one(unit["Timer"], "Unit") == f"finans-sanal-job@{job}.service"
        assert _one(unit["Install"], "WantedBy") == "timers.target"


def test_sanal_service_is_the_real_one_in_the_sanal_profile_without_ping_secrets() -> None:
    sanal = _unit(UNITS / "finans-sanal-job@.service")["Service"]
    real = _unit(UNITS / "finans-job@.service")["Service"]

    assert _one(sanal, "Environment") == "FT_PROFILE=sanal"
    for key in ("Type", "User", "Group", "WorkingDirectory", "EnvironmentFile", "ExecStart"):
        assert _one(sanal, key) == _one(real, key)
    assert {name: _one(sanal, name) for name in HARDENING} == HARDENING
    loaded = [value for name, value in sanal if name == "LoadCredential"]
    assert loaded == [f"{name}:/etc/finans/credstore/{name}" for name in SANAL_SECRETS]


def test_sanal_wrapper_runs_like_the_sanal_service() -> None:
    wrapper = (DEPLOY / "ft-sanal").read_text(encoding="utf-8")
    properties = dict(re.findall(r"-p (\w+)=(\S+)", wrapper))
    loop = re.search(r"for name in (.+); do", wrapper)

    assert properties["Environment"] == "FT_PROFILE=sanal"
    assert {name: properties.get(name) for name in HARDENING} == HARDENING
    assert loop is not None
    assert loop[1].split() == SANAL_SECRETS


@pytest.mark.parametrize("wrapper", ["ft-finans", "ft-sanal"])
def test_manual_commands_never_see_the_web_password(wrapper: str) -> None:
    """K-137: şifre kilidi kalktı; wrapper'lar yalnız işlerin sırlarını yükler."""
    assert "ft_web_password" not in (DEPLOY / wrapper).read_text(encoding="utf-8")


WEB_HARDENING = {
    **HARDENING,
    # K-106, K-136: ağa çıkar (Access anahtarları) ve 127.0.0.1'de TCP dinler.
    "RestrictAddressFamilies": "AF_INET AF_INET6 AF_UNIX",
    "CapabilityBoundingSet": "",
    "PrivateDevices": "yes",
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectKernelLogs": "yes",
    "ProtectControlGroups": "yes",
    "ProtectProc": "invisible",
    "SystemCallFilter": "@system-service",
    "MemoryDenyWriteExecute": "yes",
    "UMask": "0077",
    # K-124
    "PrivateMounts": "yes",
    "ProtectClock": "yes",
    "ProtectHostname": "yes",
    "LockPersonality": "yes",
    "RestrictNamespaces": "yes",
    "RestrictRealtime": "yes",
    "RestrictSUIDSGID": "yes",
    "RemoveIPC": "yes",
    "SystemCallArchitectures": "native",
    "SystemCallErrorNumber": "EPERM",
}
PROFILES: tuple[Literal["real", "sanal"], ...] = ("real", "sanal")


def _profile(profile: Literal["real", "sanal"]) -> Settings:
    return resolve_profile(Settings(db_path=Path(_env()["FT_DB_PATH"]), profile=profile))


def _trigger(settings: Settings) -> Path:
    requests = bootstrap.refresh_requests(settings)
    assert isinstance(requests, FileRefreshRequests)
    return requests.trigger


def test_the_web_service_runs_the_api_and_sees_only_its_session_key() -> None:
    """K-144: birimin adı kalır, `finans-api`'yi çalıştırır; soket, şifre ve ağsızlık kalktı."""
    service = _unit(UNITS / "finans-web.service")["Service"]

    assert {name: _one(service, name) for name in WEB_HARDENING} == WEB_HARDENING
    assert (_one(service, "User"), _one(service, "Group")) == ("finans", "finans")
    assert _one(service, "ExecStart") == "/opt/finans/.venv/bin/finans-api"
    assert _one(service, "EnvironmentFile") == "/etc/finans/finans.env"
    loaded = [value for name, value in service if name == "LoadCredential"]
    assert loaded == ["ft_web_session_key:/etc/finans/credstore/ft_web_session_key"]
    assert "SecretStr" in str(Settings.model_fields["web_session_key"].annotation)
    names = {name for name, _ in service}
    assert not names & {"PrivateNetwork", "RuntimeDirectory", "RuntimeDirectoryMode"}


def test_the_web_profile_is_chosen_only_in_its_drop_in() -> None:
    service = _unit(UNITS / "finans-web.service")["Service"]
    drop_in = _unit(UNITS / "finans-web.service.d" / "profil.conf")

    assert all(name != "Environment" for name, _ in service)
    assert drop_in == {"Service": [("Environment", "FT_PROFILE=sanal")]}


def test_a_read_only_connection_writes_the_shm_file_next_to_the_database(
    migrated_db: Path,
) -> None:
    shm = migrated_db.with_name(f"{migrated_db.name}-shm")
    assert not shm.exists()

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        uow.runs.recent(since=datetime(2026, 11, 1, tzinfo=UTC))
        assert shm.exists()


@pytest.mark.parametrize("profile", PROFILES)
def test_the_web_may_write_the_shm_file_and_the_request_of_its_profile(
    profile: Literal["real", "sanal"],
) -> None:
    # K-123: salt okunur bağlantı da -shm'e yazar; ProtectSystem=strict altında dizin açık olmalı.
    writable = Path(_one(_unit(UNITS / "finans-web.service")["Service"], "ReadWritePaths"))
    settings = _profile(profile)
    shm = settings.db_path.with_name(f"{settings.db_path.name}-shm")

    assert shm.parent.is_relative_to(writable)
    assert _trigger(settings).parent.is_relative_to(writable)


REFRESH_UNITS = {
    "real": ("finans-refresh", "finans-job@.service"),
    "sanal": ("finans-sanal-refresh", "finans-sanal-job@.service"),
}


@pytest.mark.parametrize("profile", PROFILES)
def test_a_refresh_request_runs_the_profiles_price_sync_like_its_jobs(
    profile: Literal["real", "sanal"],
) -> None:
    name, template = REFRESH_UNITS[profile]
    trigger = _trigger(_profile(profile))
    watcher = _unit(UNITS / f"{name}.path")
    service = _unit(UNITS / f"{name}.service")["Service"]
    job = _unit(UNITS / template)["Service"]

    assert _one(watcher["Path"], "PathExists") == str(trigger)
    assert _one(watcher["Path"], "Unit") == f"{name}.service"
    assert _one(watcher["Install"], "WantedBy") == "paths.target"
    assert _one(service, "ExecStartPre") == f"/usr/bin/rm -f {trigger}"
    assert _one(service, "ExecStart") == "/opt/finans/.venv/bin/ft job run sync-prices --bugun"
    exec_lines = {"ExecStart", "ExecStartPre"}
    assert [entry for entry in service if entry[0] not in exec_lines] == [
        entry for entry in job if entry[0] not in exec_lines
    ]


def test_web_settings_stay_empty_in_the_example() -> None:
    env = _env()
    web = (
        "FT_WEB_ORIGIN",
        "FT_WEB_HOST",
        "FT_WEB_PORT",
        "FT_CF_ACCESS_TEAM_DOMAIN",
        "FT_CF_ACCESS_AUD",
        "FT_WEB_ALLOWED_EMAIL",
    )

    assert {name: env[name] for name in web} == dict.fromkeys(web, "")
    assert "FT_WEB_SESSION_KEY" not in env
    assert "FT_WEB_ALLOWED_LOGIN" not in env
