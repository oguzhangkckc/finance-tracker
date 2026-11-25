import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finans.adapters.refresh_request import FileRefreshRequests

NOW = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)


def test_without_a_log_nothing_was_accepted(tmp_path: Path) -> None:
    assert FileRefreshRequests(tmp_path / "refresh", "sanal").accepted() == []


def test_a_request_writes_the_trigger_file_and_logs_the_moment(tmp_path: Path) -> None:
    directory = tmp_path / "refresh"
    requests = FileRefreshRequests(directory, "sanal")

    requests.request(NOW)

    assert (directory / "sanal.request").read_text(encoding="utf-8") == f"{NOW.isoformat()}\n"
    assert requests.accepted() == [NOW]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert sorted(path.name for path in directory.iterdir()) == ["sanal.log", "sanal.request"]


def test_profiles_do_not_share_requests(tmp_path: Path) -> None:
    FileRefreshRequests(tmp_path, "sanal").request(NOW)

    assert FileRefreshRequests(tmp_path, "real").accepted() == []
    assert not (tmp_path / "real.request").exists()


def test_entries_older_than_two_days_are_dropped_on_the_next_request(tmp_path: Path) -> None:
    old = NOW - timedelta(days=2)
    recent = NOW - timedelta(days=1, hours=23)
    (tmp_path / "sanal.log").write_text(f"{old.isoformat()}\n{recent.isoformat()}\n")
    requests = FileRefreshRequests(tmp_path, "sanal")

    requests.request(NOW)

    assert requests.accepted() == [recent, NOW]


def test_unreadable_and_naive_lines_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "sanal.log").write_text(f"bozuk\n2026-11-25T09:00:00\n\n{NOW.isoformat()}\n")

    assert FileRefreshRequests(tmp_path, "sanal").accepted() == [NOW]
