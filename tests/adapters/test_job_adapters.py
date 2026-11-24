import json
import logging
from pathlib import Path

import respx

from finans.adapters._http import HttpClient
from finans.adapters.healthcheck import HealthcheckPing
from finans.adapters.json_log import JsonFormatter
from finans.adapters.lock import FlockJobLock
from tests.fakes.clock import FixedClock

PING = "https://hc-ping.example/0b6f-gizli"


def test_second_holder_of_the_same_job_lock_does_not_wait(tmp_path: Path) -> None:
    lock = FlockJobLock(tmp_path / "locks")

    with (
        lock.hold("sync-prices") as first,
        lock.hold("sync-prices") as second,
        lock.hold("backup") as other,
    ):
        assert (first, second, other) == (True, False, True)

    with lock.hold("sync-prices") as again:
        assert again
    assert (tmp_path / "locks" / "sync-prices.lock").stat().st_mode & 0o777 == 0o600


@respx.mock
def test_ping_marks_failures_and_skips_undefined_checks(clock: FixedClock) -> None:
    ok = respx.get(PING).respond(200, text="OK")
    fail = respx.get(f"{PING}/fail").respond(200, text="OK")

    with HttpClient(clock, secrets=[PING]) as http:
        ping = HealthcheckPing(http, {"reports": PING})
        ping.ping("reports", ok=True)
        ping.ping("reports", ok=False)
        ping.ping("backup", ok=True)

    assert (ok.call_count, fail.call_count) == (1, 1)


def test_log_lines_are_json_with_job_fields() -> None:
    record = logging.LogRecord("finans.jobs", logging.INFO, __file__, 1, "iş bitti", None, None)
    record.job = "backup"
    record.run_id = 7
    record.status = "ok"

    line = json.loads(JsonFormatter().format(record))

    assert {
        key: line[key] for key in ("level", "logger", "message", "job", "run_id", "status")
    } == {
        "level": "INFO",
        "logger": "finans.jobs",
        "message": "iş bitti",
        "job": "backup",
        "run_id": 7,
        "status": "ok",
    }
