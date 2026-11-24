from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans.cli.main import app

runner = CliRunner()
PORTFOLIO = """
[targets]
hisse = 0.6
altin = 0.4

[[instruments]]
code = "TTE"
kind = "TEFAS_YAT"
asset_class = "hisse"

[[instruments]]
code = "ALTIN_GR"
kind = "MANUAL"
asset_class = "altin"
"""


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "var" / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(portfolio))


def _ok(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_m2_gate_transactions_in_and_value_on_any_date() -> None:
    _ok("db", "migrate")
    _ok("config", "apply")
    _ok("tx", "add", "buy", "ALTIN_GR", "10", "3000", "--date", "2026-01-05")
    _ok("tx", "add", "buy", "TTE", "100", "1.25", "--date", "2026-01-06")
    assert "Fiyat kaydedildi." in _ok("price", "set", "ALTIN_GR", "2026-03-01", "3300")

    march = _ok("value", "--on", "2026-03-10")
    assert "Değerleme: 2026-03-10" in march
    assert "ALTIN_GR  10 adet × 3300 (2026-03-01) = 33000  maliyet 30000" in march
    assert "TTE  100 adet  fiyat yok  maliyet 125" in march
    assert "Toplam değer: 33000 (fiyatı olan varlıkların maliyeti 30000)" in march
    assert "Basit getiri: %10.00" in march
    assert "Fiyatı eksik: TTE" in march

    assert "Pozisyon yok." in _ok("value", "--on", "2026-01-04")


def test_price_set_reports_revision_and_rejects_tefas() -> None:
    _ok("config", "apply")
    _ok("price", "set", "ALTIN_GR", "2026-03-01", "3300")
    assert "Fiyat aynı; değişiklik yok." in _ok("price", "set", "ALTIN_GR", "2026-03-01", "3300.0")
    assert "Fiyat güncellendi; önceki değer 3300." in _ok(
        "price", "set", "ALTIN_GR", "2026-03-01", "3310"
    )
    rejected = runner.invoke(app, ["price", "set", "TTE", "2026-03-01", "1"])
    assert rejected.exit_code == 1
    assert "elle girilemez" in rejected.output
