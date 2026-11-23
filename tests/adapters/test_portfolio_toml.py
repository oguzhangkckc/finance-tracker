from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.portfolio_toml import TomlPortfolioSource
from finans.domain.models import Instrument, InstrumentKind
from finans.domain.portfolio import AlertThresholds, ConfigError

D = Decimal
VALID = """
[contribution]
monthly = 15000.50

[alerts]
open_above = 0.06

[targets]
hisse = 0.6
dusuk_risk = 0.4

[[instruments]]
code = "TTE"
kind = "TEFAS_YAT"
asset_class = "hisse"
name = "Hisse fonu"

[[instruments]]
code = "AFT"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"
category = "para_piyasasi"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "portfolio.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _issues(tmp_path: Path, text: str) -> list[str]:
    with pytest.raises(ConfigError) as caught:
        TomlPortfolioSource().load(_write(tmp_path, text))
    return [str(issue) for issue in caught.value.issues]


def test_valid_file_is_parsed_with_exact_decimals(tmp_path: Path) -> None:
    config = TomlPortfolioSource().load(_write(tmp_path, VALID))
    assert config.instruments == (
        Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse", name="Hisse fonu"),
        Instrument("AFT", InstrumentKind.TEFAS_YAT, "dusuk_risk", category="para_piyasasi"),
    )
    assert config.targets == {"hisse": D("0.6"), "dusuk_risk": D("0.4")}
    assert type(config.targets["hisse"]) is Decimal
    assert config.monthly_contribution == D("15000.50")
    assert config.alerts == AlertThresholds(open_above=D("0.06"))


def test_all_structural_and_semantic_errors_are_reported_at_once(tmp_path: Path) -> None:
    text = """
[targets]
hisse = 0.3333
dusuk_risk = "0.3333"
altin = 0.3333

[[instruments]]
code = "TTE"
kind = "TEFAS"
asset_class = "hisse"
renk = "mavi"

[[instruments]]
kind = "MANUAL"
asset_class = "altin"

[hedefler]
x = 1
"""
    assert _issues(tmp_path, text) == [
        "hedefler: tanınmayan bölüm; geçerli bölümler: alerts, contribution, instruments, targets.",
        'instruments[0].kind: "TEFAS" geçersiz; '
        "TEFAS_YAT, TEFAS_EMK, TEFAS_BYF ya da MANUAL olmalı.",
        "instruments[0].renk: tanınmayan alan.",
        "instruments[1].code: zorunlu alan eksik.",
        'targets.dusuk_risk: sayı olmalı (tırnaksız), "0.3333" verildi.',
        "targets.dusuk_risk: bu sınıfta tanımlı varlık yok.",
    ]


BASE = (
    '[targets]\nhisse = 1\n\n[[instruments]]\ncode = "TTE"\nkind = "TEFAS_YAT"\n'
    'asset_class = "hisse"\n'
)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ("[contribution]\nmonthly = true\n", "contribution.monthly: sayı olmalı, True verildi."),
        ("[contribution]\nweekly = 1\n", "contribution.weekly: tanınmayan alan."),
        ("[alerts]\nreminder_days = 1.5\n", "alerts.reminder_days: tam sayı olmalı"),
        (
            '[alerts]\nopen_above = "x"\n',
            'alerts.open_above: sayı olmalı (tırnaksız), "x" verildi.',
        ),
        ("[alerts]\nsilence = 1\n", "alerts.silence: tanınmayan alan."),
        (
            "[[instruments]]\ncode = 5\n",
            "instruments[1].code: boş olmayan metin olmalı, 5 verildi.",
        ),
    ],
)
def test_value_errors_name_the_field(tmp_path: Path, extra: str, expected: str) -> None:
    assert any(issue.startswith(expected) for issue in _issues(tmp_path, BASE + extra))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('targets = 1\n[[instruments]]\ncode = "A"\n', "targets: [targets] tablosu olmalı."),
        ("instruments = 1\n[targets]\nhisse = 1\n", "instruments: [[instruments]] tabloları"),
        ("contribution = 1\n" + BASE, "contribution: [contribution] tablosu olmalı."),
        ("alerts = 1\n" + BASE, "alerts: [alerts] tablosu olmalı."),
    ],
)
def test_wrong_section_shapes_are_reported(tmp_path: Path, text: str, expected: str) -> None:
    assert any(issue.startswith(expected) for issue in _issues(tmp_path, text))


def test_missing_file_and_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="dosya bulunamadı"):
        TomlPortfolioSource().load(tmp_path / "yok.toml")
    (issue,) = _issues(tmp_path, "[targets\n")
    assert "TOML okunamadı" in issue
