from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans import bootstrap
from finans.cli.main import app
from finans.domain.models import CpiPoint, PricePoint, YearMonth
from finans.ports.clock import Clock
from finans.ports.sources import (
    CpiSource,
    FetchResult,
    PriceSource,
    RawPayload,
    SourceBlocked,
    SourceError,
)
from finans.settings import Settings
from tests.fakes.sources import FakeCpiSource, FakePriceSource

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


PORTFOLIO = """
[targets]
karma = 1

[[instruments]]
code = "BCO"
kind = "TEFAS_YAT"
asset_class = "karma"
"""
RANGE = ["--from", "2026-11-01", "--to", "2026-11-24"]


@pytest.fixture
def portfolio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "portfolio.toml"
    path.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(path))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0


def _use_prices(monkeypatch: pytest.MonkeyPatch, source: FakePriceSource) -> None:
    @contextmanager
    def fake(_settings: Settings, _clock: Clock) -> Iterator[PriceSource]:
        yield source

    monkeypatch.setattr(bootstrap, "price_source", fake)


def _prices(*values: tuple[date, str]) -> FetchResult[PricePoint]:
    points = [PricePoint("BCO", day, Decimal(price), "tefas") for day, price in values]
    return FetchResult(points, [RawPayload("tefas", "k", NOW, b"{}")])


@pytest.mark.usefixtures("portfolio")
def test_sync_prices_reports_each_fund_and_revisions(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_prices(monkeypatch, FakePriceSource({"BCO": _prices((date(2026, 11, 20), "1.744"))}))
    first = runner.invoke(app, ["sync", "prices", *RANGE])
    assert first.exit_code == 0, first.output
    assert "istekler arası en az 10 sn" in first.output
    assert (
        "✓ BCO (2026-11-01 ile 2026-11-24 arası): 1 gün alındı; eklenen 1, değişmeyen 0, revize 0"
        in (first.output)
    )
    assert "Sonuç: tamam" in first.output

    _use_prices(monkeypatch, FakePriceSource({"BCO": _prices((date(2026, 11, 20), "1.744322"))}))
    second = runner.invoke(app, ["sync", "prices", *RANGE])
    assert "  revize 2026-11-20: 1.744 → 1.744322" in second.output


@pytest.mark.usefixtures("portfolio")
def test_failed_fund_exits_with_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_prices(monkeypatch, FakePriceSource({"BCO": SourceError("TEFAS: Sistem Hatası!!")}))
    result = runner.invoke(app, ["sync", "prices", *RANGE])
    assert result.exit_code == 1
    assert "✗ BCO: TEFAS: Sistem Hatası!!" in result.output
    assert "Sonuç: kısmi" in result.output


@pytest.mark.usefixtures("portfolio")
def test_block_is_explained_and_not_worked_around(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_prices(monkeypatch, FakePriceSource({"BCO": SourceBlocked("HTTP 403: Access denied")}))
    result = runner.invoke(app, ["sync", "prices", *RANGE])
    assert result.exit_code == 1
    assert "Durduruldu: TEFAS isteği reddetti ya da sınırladı" in result.output
    assert "engel aşılmaya çalışılmadı" in result.output


def test_without_funds_it_says_how_to_add_them(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_prices(monkeypatch, FakePriceSource())
    result = runner.invoke(app, ["sync", "prices"])
    assert result.exit_code == 0, result.output
    assert "Senkronize edilecek TEFAS fonu yok" in result.output


@pytest.mark.usefixtures("portfolio")
def test_unknown_code_and_bad_dates_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_prices(monkeypatch, FakePriceSource())
    unknown = runner.invoke(app, ["sync", "prices", "--code", "YOK"])
    assert unknown.exit_code == 1
    assert "YOK tanımlı değil" in unknown.output
    assert runner.invoke(app, ["sync", "prices", "--from", "2026-13-01"]).exit_code == 2


@pytest.mark.usefixtures("portfolio")
def test_sync_prices_shows_manual_prices_replaced_by_tefas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert runner.invoke(app, ["price", "set", "BCO", "2026-11-19", "1.7443"]).exit_code == 0
    assert runner.invoke(app, ["price", "set", "BCO", "2026-11-20", "1.75"]).exit_code == 0
    prices = _prices((date(2026, 11, 19), "1.744322"), (date(2026, 11, 20), "1.73"))
    _use_prices(monkeypatch, FakePriceSource({"BCO": prices}))

    result = runner.invoke(app, ["sync", "prices", *RANGE])

    assert "  elle fiyat yerine TEFAS 2026-11-19: 1.7443 → 1.744322" in result.output
    assert (
        "Uyarı: [elle ve TEFAS fiyatı] BCO 2026-11-20: elle girilen 1.75 TEFAS fiyatıyla (1.73) "
        "uyuşmuyor" in result.output
    )
