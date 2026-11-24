import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

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
def portfolio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "portfolio.toml"
    path.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(path))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0


@pytest.mark.usefixtures("portfolio")
def test_job_runs_once_per_day_and_is_listed() -> None:
    first = runner.invoke(app, ["job", "run", "weekly-report", "--logical-date", "2026-11-29"])
    second = runner.invoke(app, ["job", "run", "weekly-report", "--logical-date", "2026-11-29"])

    assert first.exit_code == 0, first.output
    assert "weekly-report 2026-11-29: tamam" in first.output
    assert "  gönderim: haftalık rapor kapalı (FT_WEEKLY_REPORT_ENABLED)" in first.output
    assert "weekly-report 2026-11-29: bu gün için zaten tamamlanmış; atlandı" in second.output
    listed = runner.invoke(app, ["job", "list", "--days", "36500"])
    assert "#1 weekly-report 2026-11-29 ok" in listed.output


@pytest.mark.usefixtures("portfolio")
def test_failed_job_exits_with_one_and_says_why() -> None:
    result = runner.invoke(app, ["job", "run", "backup", "--logical-date", "2026-11-29"])

    assert result.exit_code == 1
    assert "backup 2026-11-29: başarısız" in result.output
    assert "  hata: JobError: yedek işi bu sürümde yok (K-82)" in result.output
