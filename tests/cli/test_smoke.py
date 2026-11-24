from contextlib import closing
from importlib.metadata import version
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from finans import bootstrap
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import Migration, bundled
from finans.cli.agent import app as agent_app
from finans.cli.main import app as ft_app

runner = CliRunner()

AGENT_READ_ONLY_COMMANDS = {"summary", "holdings", "alerts", "report", "ppk-text"}


def test_ft_version() -> None:
    result = runner.invoke(ft_app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == version("finans-takip")


def test_ft_agent_version() -> None:
    result = runner.invoke(agent_app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == version("finans-takip")


def test_db_migrate_creates_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "var" / "finans.db"
    monkeypatch.setenv("FT_DB_PATH", str(db))

    result = runner.invoke(ft_app, ["db", "migrate"])

    assert result.exit_code == 0, result.output
    assert db.exists()
    with closing(connect(db, readonly=True)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_db_migrate_prints_the_backup_taken_before_pending_migrations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = tmp_path / "finans.db"
    monkeypatch.setenv("FT_DB_PATH", str(db))
    first = runner.invoke(ft_app, ["db", "migrate"])
    assert first.exit_code == 0, first.output
    assert "yedek" not in first.output
    version = len(bundled()) + 1
    second_migration = Migration(
        version, f"{version:04d}_b.sql", "CREATE TABLE b (id INTEGER) STRICT;", "0" * 64
    )
    monkeypatch.setattr(bootstrap, "bundled", lambda: [*bundled(), second_migration])

    result = runner.invoke(ft_app, ["db", "migrate"])

    assert result.exit_code == 0, result.output
    assert f"Uygulanan migration'lar: {version}" in result.output
    assert f"Migration öncesi yedek: {tmp_path / 'backups' / 'finans-'}" in result.output
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_db_migrate_without_settings_exits_with_clear_message() -> None:
    result = runner.invoke(ft_app, ["db", "migrate"])
    assert result.exit_code == 2
    assert "db_path" in result.output
    assert "FT_" in result.output


def test_db_migrate_reports_migration_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = tmp_path / "finans.db"
    with closing(connect(db)) as conn:
        conn.execute("PRAGMA user_version = 99")
    monkeypatch.setenv("FT_DB_PATH", str(db))

    result = runner.invoke(ft_app, ["db", "migrate"])

    assert result.exit_code == 1
    assert "Migration hatası" in result.output
    assert "eski kodla açılmaz" in result.output


def test_ft_agent_exposes_only_read_only_commands() -> None:
    command = typer.main.get_command(agent_app)
    subcommands = set(getattr(command, "commands", {}))
    assert subcommands <= AGENT_READ_ONLY_COMMANDS
