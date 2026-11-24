from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans import bootstrap
from finans.cli.main import app
from finans.domain.models import CpiPoint, YearMonth
from finans.ports.clock import Clock
from finans.ports.sources import CpiSource, FetchResult, RawPayload, SourceError
from finans.settings import Settings
from tests.fakes.sources import FakeCpiSource

runner = CliRunner()
KEY = "cok-gizli-anahtar"
NOW = datetime(2026, 11, 24, 7, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))


def _use(monkeypatch: pytest.MonkeyPatch, source: FakeCpiSource) -> None:
    @contextmanager
    def fake(_settings: Settings, _clock: Clock) -> Iterator[CpiSource]:
        yield source

    monkeypatch.setattr(bootstrap, "cpi_source", fake)


def _result(*values: tuple[str, str]) -> FetchResult[CpiPoint]:
    points = [CpiPoint(YearMonth.parse(period), Decimal(index)) for period, index in values]
    return FetchResult(points, [RawPayload("evds", "k", NOW, b"{}")])


def test_sync_cpi_reports_counts_revisions_and_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, FakeCpiSource(_result(("2026-09", "104.1"), ("2026-10", "105"))))
    first = runner.invoke(app, ["sync", "cpi"])
    assert first.exit_code == 0, first.output
    assert (
        "TÜFE TP.TUKFIY2025.GENEL: 2 dönem alındı; eklenen 2, değişmeyen 0, revize 0"
        in first.output
    )
    assert "Son dönem: 2026-10" in first.output

    source = FakeCpiSource(_result(("2026-09", "104.2"), ("2026-10", "105")))
    _use(monkeypatch, source)
    second = runner.invoke(app, ["sync", "cpi", "--from", "2026-09"])
    assert second.exit_code == 0, second.output
    assert source.calls[0][1] == YearMonth(2026, 9)
    assert "Revize 2026-09: 104.1 → 104.2" in second.output


def test_default_start_is_the_whole_history(monkeypatch: pytest.MonkeyPatch) -> None:
    source = FakeCpiSource(_result())
    _use(monkeypatch, source)
    assert runner.invoke(app, ["sync", "cpi"]).exit_code == 0
    assert source.calls[0][1] == YearMonth(2005, 1)


def test_source_errors_exit_with_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, FakeCpiSource(SourceError("EVDS: HTTP 403: anahtar geçersiz")))
    result = runner.invoke(app, ["sync", "cpi"])
    assert result.exit_code == 1
    assert "Hata: EVDS: HTTP 403: anahtar geçersiz" in result.output


def test_invalid_period_is_rejected() -> None:
    result = runner.invoke(app, ["sync", "cpi", "--from", "2026-13"])
    assert result.exit_code == 2
    assert "YYYY-AA" in result.output


def test_missing_key_explains_what_to_do() -> None:
    result = runner.invoke(app, ["sync", "cpi"])
    assert result.exit_code == 1
    assert "FT_EVDS_API_KEY tanımlı değil" in result.output


def test_doctor_shows_whether_the_key_is_defined_never_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert runner.invoke(app, ["db", "migrate"]).exit_code == 0
    missing = runner.invoke(app, ["doctor"])
    assert "! EVDS anahtarı: FT_EVDS_API_KEY tanımlı değil" in missing.output
    assert "! TÜFE: veri yok; `ft sync cpi` çalıştır" in missing.output

    monkeypatch.setenv("FT_EVDS_API_KEY", KEY)
    defined = runner.invoke(app, ["doctor"])
    assert "✓ EVDS anahtarı: tanımlı" in defined.output
    assert KEY not in defined.output
