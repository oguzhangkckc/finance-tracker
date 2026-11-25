"""`ft ayar` (K-127): geçerli ayar, geçmiş, yürürlük tarihli değişiklik ve vazgeçme; CLI'da
sayılar noktalıdır."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finans import bootstrap
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.cli.main import app
from tests.fakes.clock import FixedClock

runner = CliRunner()
D = Decimal
NOW = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
PORTFOLIO = """
[contribution]
monthly = 1000
payday = 15

[targets]
hisse = 0.6
dusuk_risk = 0.4

[[instruments]]
code = "XHT"
kind = "TEFAS_YAT"
asset_class = "hisse"

[[instruments]]
code = "XPP"
kind = "TEFAS_YAT"
asset_class = "dusuk_risk"
"""
START_VALUES = [
    "  Maaş günü: 15",
    "  Aylık katkı: 1000",
    "  Hedefler: hisse=0.6 dusuk_risk=0.4",
]


@pytest.fixture
def unapplied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    portfolio = tmp_path / "portfolio.toml"
    portfolio.write_text(PORTFOLIO, encoding="utf-8")
    monkeypatch.setenv("FT_DB_PATH", str(tmp_path / "finans.db"))
    monkeypatch.setenv("FT_PORTFOLIO_PATH", str(portfolio))
    monkeypatch.setattr(bootstrap, "system_clock", lambda: FixedClock(NOW))
    assert runner.invoke(app, ["db", "migrate"]).exit_code == 0
    return tmp_path / "finans.db"


@pytest.fixture
def db(unapplied: Path) -> Path:
    assert runner.invoke(app, ["config", "apply"]).exit_code == 0
    return unapplied


def _ok(*args: str) -> str:
    result = runner.invoke(app, ["ayar", *args])
    assert result.exit_code == 0, result.output
    return result.output


def _versions(db: Path) -> int:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        return len(uow.settings.list())


@pytest.mark.usefixtures("db")
def test_show_gives_the_starting_version_after_the_first_apply() -> None:
    assert _ok("goster").splitlines() == [
        "Geçerli ayar: başlangıç sürümü (portfolio.toml)",
        *START_VALUES,
    ]


def test_a_planned_contribution_is_saved_from_the_cli_and_shown(db: Path) -> None:
    saved = _ok("katki", "1200", "--tarih", "2027-01-01")

    assert saved == "Ayar sürümü #2 kaydedildi; yürürlük 2027-01-01: aylık katkı 1000 → 1200\n"
    assert _ok("goster").splitlines() == [
        "Geçerli ayar: başlangıç sürümü (portfolio.toml)",
        *START_VALUES,
        "Planlanan: #2, yürürlük 2027-01-01: aylık katkı 1000 → 1200",
    ]
    with SqliteUnitOfWork(db, readonly=True) as uow:
        last = uow.settings.list()[-1]
    assert (last.source, last.version.monthly_contribution) == ("cli", D(1200))


def test_a_change_from_today_becomes_the_current_setting(db: Path) -> None:
    saved = _ok("hedef", "hisse=0.7", "dusuk_risk=0.3", "--tarih", "2026-11-25")

    assert saved == (
        "Ayar sürümü #2 kaydedildi; yürürlük 2026-11-25:"
        " hedefler hisse=0.6 dusuk_risk=0.4 → hisse=0.7 dusuk_risk=0.3\n"
    )
    assert _ok("goster").splitlines()[0] == "Geçerli ayar: #2, yürürlük 2026-11-25"
    assert _versions(db) == 2


@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        (
            ["maas-gunu", "20", "--tarih", "2026-12-10"],
            1,
            "  - effective_from: maaş günü değişikliği yalnız bir ayın 1'inden geçerli olabilir.",
        ),
        (
            ["hedef", "hisse=0.6", "dusuk_risk=0.3", "--tarih", "2026-11-25"],
            1,
            "  - targets: hedeflerin toplamı tam 1 olmalı, şu an 0.9.",
        ),
        (
            ["katki", "1000", "--tarih", "2026-11-25"],
            1,
            "  - ayar: o günkü ayarla aynı; yeni sürüm gerekmiyor.",
        ),
        (
            ["katki", "1200", "--tarih", "2026-11-24"],
            1,
            "  - effective_from: yürürlük günü en erken bugün (2026-11-25) olabilir.",
        ),
        (
            ["hedef", "hisse=0,7", "dusuk_risk=0,3", "--tarih", "2026-11-25"],
            2,
            "hisse: ondalık ayırıcı nokta olmalı; 0,7 yerine 0.7 yaz.",
        ),
        (
            ["hedef", "hisse", "--tarih", "2026-11-25"],
            2,
            "Hedef SINIF=ORAN biçiminde yazılır; 'hisse' verildi.",
        ),
        (
            ["hedef", "hisse=0.5", "hisse=0.5", "--tarih", "2026-11-25"],
            2,
            "hisse iki kez verildi.",
        ),
        (
            ["katki", "1200", "--tarih", "1 Ocak"],
            2,
            "Tarih YYYY-AA-GG biçiminde olmalı, '1 Ocak' verildi.",
        ),
    ],
)
def test_a_broken_change_is_refused_and_nothing_is_written(
    db: Path, args: list[str], code: int, message: str
) -> None:
    result = runner.invoke(app, ["ayar", *args])

    assert result.exit_code == code
    assert message in result.output.splitlines()
    if code == 1:
        assert "Ayar kaydedilmedi; 1 hata var:" in result.output
    assert _versions(db) == 1


@pytest.mark.usefixtures("db")
def test_without_the_option_a_later_version_reverts_the_change_and_is_warned_about() -> None:
    _ok("hedef", "hisse=0.7", "dusuk_risk=0.3", "--tarih", "2027-03-01")

    saved = _ok("katki", "1200", "--tarih", "2027-01-01")

    assert saved.splitlines()[1] == (
        "Uyarı: yürürlüğü 2027-03-01 olan planlanan sürüm (#2) bu değişikliği taşımıyor;"
        " o günden itibaren aylık katkı 1000 olur. Taşımak için komut `--sonrakilere-de` ile"
        " verilir; şimdi düzeltmek için #2 sürümünden vazgeçip yeniden ekle."
    )
    assert "Planlanan: #2, yürürlük 2027-03-01" in _ok("goster")


def test_with_the_option_the_change_is_carried_into_the_later_version(db: Path) -> None:
    _ok("hedef", "hisse=0.7", "dusuk_risk=0.3", "--tarih", "2027-03-01")

    saved = _ok("katki", "1200", "--tarih", "2027-01-01", "--sonrakilere-de")

    assert saved.splitlines() == [
        "Ayar sürümü #3 kaydedildi; yürürlük 2027-01-01: aylık katkı 1000 → 1200",
        "Sonraki sürüme taşındı: #2 yerine #4, yürürlük 2027-03-01: aylık katkı 1000 → 1200",
    ]
    with SqliteUnitOfWork(db, readonly=True) as uow:
        rows = uow.settings.list()
    assert rows[1].cancel_reason == "yeni değişiklik taşındı: #3"
    assert (rows[3].version.monthly_contribution, rows[3].version.targets) == (
        D(1200),
        {"hisse": D("0.7"), "dusuk_risk": D("0.3")},
    )


@pytest.mark.usefixtures("db")
def test_history_lists_every_version_and_only_a_planned_one_can_be_cancelled() -> None:
    _ok("katki", "1200", "--tarih", "2027-01-01")
    _ok("maas-gunu", "20", "--tarih", "2027-02-01")

    in_force = runner.invoke(app, ["ayar", "vazgec", "1", "--gerekce", "yanlış"])
    cancelled = _ok("vazgec", "3", "--gerekce", "yanlış ay")

    assert in_force.exit_code == 1
    assert (
        "Hata: 1 numaralı ayar sürümü yürürlüğe girmiş; vazgeçilemez. Değiştirmek için yeni bir"
        " sürüm ekle." in in_force.output
    )
    assert cancelled == "Vazgeçildi: ayar sürümü #3 (yürürlük 2027-02-01 olacaktı).\n"
    assert _ok("gecmis").splitlines() == [
        "#1  başlangıç (portfolio.toml)  geçerli  toml  2026-11-25 13:00"
        "  maaş günü 15 · aylık katkı 1000 · hedefler hisse=0.6 dusuk_risk=0.4",
        "#2  yürürlük 2027-01-01  planlandı  cli  2026-11-25 13:00  aylık katkı 1000 → 1200",
        "#3  yürürlük 2027-02-01  vazgeçildi (yanlış ay)  cli  2026-11-25 13:00  maaş günü 15 → 20",
    ]


@pytest.mark.usefixtures("unapplied")
def test_before_the_first_apply_the_toml_is_shown_and_changes_are_refused() -> None:
    refused = runner.invoke(app, ["ayar", "katki", "1200", "--tarih", "2026-11-25"])

    assert refused.exit_code == 1
    assert (
        "Hata: Ayarların başlangıç sürümü yok; önce `ft config apply` çalıştır." in refused.output
    )
    assert _ok("goster").splitlines() == [
        "Ayar sürümü yok; portfolio.toml kullanılıyor. Başlangıç sürümünü `ft config apply` yazar.",
        *START_VALUES,
    ]
    assert _ok("gecmis") == "Ayar sürümü yok; başlangıç sürümünü `ft config apply` yazar.\n"


@pytest.mark.parametrize(
    ("extra", "later"),
    [
        (
            [],
            "Uyarı: yürürlüğü 2027-03-01 olan planlanan sürüm (#2) bu değişikliği taşımıyor;"
            " o günden itibaren aylık katkı 1000 olur. Taşımak için komutu `--sonrakilere-de`"
            " ile ver.",
        ),
        (
            ["--sonrakilere-de"],
            "Sonraki sürüme taşınacak: #2, yürürlük 2027-03-01: aylık katkı 1000 → 1200",
        ),
    ],
)
def test_a_dry_run_shows_the_same_preview_and_warnings_without_writing(
    db: Path, extra: list[str], later: str
) -> None:
    _ok("hedef", "hisse=0.7", "dusuk_risk=0.3", "--tarih", "2027-03-01")

    shown = _ok("katki", "1200", "--tarih", "2027-01-01", "--deneme", *extra)

    assert shown.splitlines() == [
        "Önizleme (kaydedilmedi); yürürlük 2027-01-01: aylık katkı 1000 → 1200",
        later,
    ]
    assert _versions(db) == 2


def test_a_dry_run_of_a_broken_change_shows_the_issues(db: Path) -> None:
    result = runner.invoke(app, ["ayar", "maas-gunu", "20", "--tarih", "2026-12-10", "--deneme"])

    assert result.exit_code == 1
    assert (
        "  - effective_from: maaş günü değişikliği yalnız bir ayın 1'inden geçerli olabilir."
        in result.output.splitlines()
    )
    assert _versions(db) == 1
