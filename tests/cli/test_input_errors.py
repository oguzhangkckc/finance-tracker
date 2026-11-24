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
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(portfolio))
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0


def _add(units: str, price: str, *extra: str) -> tuple[int, str]:
    result = runner.invoke(
        app, ["tx", "add", "buy", "XHT", units, price, "--date", "2026-06-15", *extra]
    )
    return result.exit_code, result.output


@pytest.mark.parametrize(
    ("units", "price", "extra", "message"),
    [
        ("12,5", "10", (), "units: ondalık ayırıcı nokta olmalı; 12,5 yerine 12.5 yaz."),
        ("10", "abc", (), "price: sayı olmalı, 'abc' verildi."),
        ("10", "1.234,5", (), "price: sayı olmalı, '1.234,5' verildi."),
        ("10", "1", ("--fee", "0,5"), "fee: ondalık ayırıcı nokta olmalı; 0,5 yerine 0.5 yaz."),
    ],
)
def test_malformed_numbers_are_usage_errors(
    units: str, price: str, extra: tuple[str, ...], message: str
) -> None:
    code, output = _add(units, price, *extra)

    assert code == 2
    assert message in output


@pytest.mark.parametrize("text", ["2026-6-15", "20260615", "2026-02-30", "15.06.2026"])
def test_dates_must_be_written_exactly_as_iso(text: str) -> None:
    result = runner.invoke(app, ["tx", "add", "buy", "XHT", "10", "1", "--date", text])

    assert result.exit_code == 2
    assert f"Tarih YYYY-AA-GG biçiminde olmalı, {text!r} verildi." in result.output


def test_invalid_period_is_a_usage_error() -> None:
    result = runner.invoke(app, ["sync", "cpi", "--from", "2026-13"])

    assert result.exit_code == 2
    assert "Dönem YYYY-AA biçiminde geçerli bir ay olmalı, '2026-13' verildi." in result.output


def test_not_a_number_is_rejected_by_the_domain_check() -> None:
    code, output = _add("NaN", "10")

    assert code == 1
    assert "Hata: units sonlu bir sayı olmalı: NaN" in output


def test_exponent_notation_is_accepted() -> None:
    code, output = _add("1e3", "10")

    assert code == 0, output
    listed = runner.invoke(app, ["tx", "list"])
    assert "#1  2026-06-15  XHT  BUY  1000 × 10  komisyon 0" in listed.output
