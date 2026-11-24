from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.portfolio_toml import TomlPortfolioSource
from finans.domain.models import Instrument, InstrumentKind
from finans.domain.portfolio import AlertThresholds, ConfigError, QualityThresholds

D = Decimal
EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "portfolio.example.toml"
FICTIONAL_CODES = {"XHT", "XHY", "XPP", "XAL", "XAC"}
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


def test_example_file_is_valid_and_uses_only_fictional_codes() -> None:
    config = TomlPortfolioSource().load(EXAMPLE)

    assert [i.code for i in config.instruments] == ["XHT", "XHY", "XPP", "XAL", "XAC"]
    assert {i.code for i in config.instruments} <= FICTIONAL_CODES
    assert config.targets == {
        "hisse_tr": D("0.30"),
        "hisse_yabanci": D("0.15"),
        "dusuk_risk": D("0.40"),
        "altin": D("0.15"),
    }
    assert (config.monthly_contribution, config.payday) == (D(10000), 15)
    assert [i.code for i in config.instruments if not i.allocation] == ["XAC"]
    assert config.alerts == AlertThresholds()


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
        "hedefler: tanınmayan bölüm; geçerli bölümler: alerts, contribution, instruments, quality, "
        "targets.",
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
        ("[quality]\nstale = 3\n", "quality.stale: tanınmayan alan."),
        ('[quality.jump]\nhisse = "0.1"\n', 'quality.jump.hisse: sayı olmalı (tırnaksız), "0.1"'),
        ("[quality.jump]\nhisse = 0\n", "quality.jump.hisse: 0 ile 1 arasında olmalı"),
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
        ("quality = 1\n" + BASE, "quality: [quality] tablosu olmalı."),
        ("[quality]\njump = 1\n" + BASE, "quality.jump: [quality.jump] tablosu olmalı."),
    ],
)
def test_wrong_section_shapes_are_reported(tmp_path: Path, text: str, expected: str) -> None:
    assert any(issue.startswith(expected) for issue in _issues(tmp_path, text))


def test_missing_file_and_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="dosya bulunamadı"):
        TomlPortfolioSource().load(tmp_path / "yok.toml")
    (issue,) = _issues(tmp_path, "[targets\n")
    assert "TOML okunamadı" in issue


def test_quality_thresholds_default_and_merge_with_overrides(tmp_path: Path) -> None:
    assert TomlPortfolioSource().load(_write(tmp_path, BASE)).quality == QualityThresholds()

    config = TomlPortfolioSource().load(
        _write(tmp_path, BASE + "[quality.jump]\nhisse = 0.15\npara_piyasasi = 0.02\n")
    )

    assert config.quality.jump == {
        "para_piyasasi": D("0.02"),
        "default": D("0.10"),
        "hisse": D("0.15"),
    }


def test_missing_contribution_is_undefined_and_payday_is_read(tmp_path: Path) -> None:
    without = VALID.replace("[contribution]\nmonthly = 15000.50\n", "")
    config = TomlPortfolioSource().load(_write(tmp_path, without))
    assert (config.monthly_contribution, config.payday) == (None, None)

    zero = VALID.replace("monthly = 15000.50\n", "monthly = 0\npayday = 15\n")
    config = TomlPortfolioSource().load(_write(tmp_path, zero))
    assert (config.monthly_contribution, config.payday) == (D(0), 15)


@pytest.mark.parametrize(
    ("contribution", "expected"),
    [
        (
            "monthly = 1\npayday = 32\n",
            "contribution.payday: 1 ile 31 arasında olmalı; 32 verildi.",
        ),
        ('monthly = 1\npayday = "15"\n', "contribution.payday: tam sayı olmalı, '15' verildi."),
        (
            "payday = 15\n",
            "contribution.payday: maaş günü için contribution.monthly da tanımlı olmalı.",
        ),
    ],
)
def test_payday_problems_are_reported(tmp_path: Path, contribution: str, expected: str) -> None:
    text = VALID.replace("monthly = 15000.50\n", contribution)
    assert expected in _issues(tmp_path, text)


def test_out_of_allocation_instrument_needs_no_target(tmp_path: Path) -> None:
    text = VALID + (
        '\n[[instruments]]\ncode = "ACL"\nkind = "TEFAS_YAT"\n'
        'asset_class = "acil_durum"\nallocation = false\n'
    )
    config = TomlPortfolioSource().load(_write(tmp_path, text))
    assert config.instruments[-1] == Instrument(
        "ACL", InstrumentKind.TEFAS_YAT, "acil_durum", allocation=False
    )


def test_allocation_must_be_a_boolean(tmp_path: Path) -> None:
    text = VALID.replace('name = "Hisse fonu"', 'name = "Hisse fonu"\nallocation = "hayır"')
    assert "instruments[0].allocation: true ya da false olmalı, 'hayır' verildi." in _issues(
        tmp_path, text
    )


def test_target_class_needs_an_in_allocation_instrument(tmp_path: Path) -> None:
    text = VALID.replace(
        'category = "para_piyasasi"', 'category = "para_piyasasi"\nallocation = false'
    )
    expected = (
        "targets.dusuk_risk: bu sınıfta dağılım içi varlık yok; "
        "allocation = false olanlar sayılmaz."
    )
    assert expected in _issues(tmp_path, text)
