"""Deploy çalıştırıcısının hazırlık kısmı (K-134, K-135): istek, dondurma, doğrulama, canlıya
dokunmayan hazırlık, elle kurulum kuralları ve sonuç dosyası. Git gerçek, `uv` sahtedir."""

import json
import os
import shutil
import stat
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import istek
import kur
from tests.deploy_ci.conftest import Pi

SHA = "0123456789abcdef0123456789abcdef01234567"
IDENT = "f" * 32
TODAY = date(2026, 11, 25)


def _verify_fails(pi: Pi, sha: str) -> kur.Sonuc:
    with pytest.raises(kur.Durdur) as stopped:
        kur.verify(pi.paths, sha)
    return stopped.value.sonuc


def test_both_scripts_use_the_same_exit_codes() -> None:
    assert [(k.name, k.value) for k in kur.Kod] == [(k.name, k.value) for k in istek.Kod]


def test_a_request_is_read_once_and_removed(pi: Pi) -> None:
    pi.paths.istek.write_text(f"{SHA}\n{IDENT}\n", encoding="ascii")

    assert kur.read_request(pi.paths) == (SHA, IDENT)
    assert not pi.paths.istek.exists()
    assert kur.read_request(pi.paths) is None


@pytest.mark.parametrize("content", [f"{SHA}\n", f"{SHA.upper()}\n{IDENT}\n", f"{SHA}\nkimlik\n"])
def test_a_malformed_request_is_dropped(pi: Pi, content: str) -> None:
    pi.paths.istek.write_text(content, encoding="ascii")

    assert kur.read_request(pi.paths) is None
    assert not pi.paths.istek.exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "# kabul bitince silinecek\nbitis=2026-12-08\nsebep=M4 kabul süresi\n",
            "⏸ Deploy dondurulmuş: M4 kabul süresi (2026-12-08 dahil). 0123456 kurulmadı.",
        ),
        (
            "bitis=2026-11-25\nsebep=bakım\n",
            "⏸ Deploy dondurulmuş: bakım (2026-11-25 dahil). 0123456 kurulmadı.",
        ),
        (
            "sebep=D1 kurulumu\n",
            "⏸ Deploy dondurulmuş: D1 kurulumu (süresiz). 0123456 kurulmadı.",
        ),
        ("", "⏸ Deploy dondurulmuş: sebep yazılmamış (süresiz). 0123456 kurulmadı."),
        (
            "bitis=8 Aralık\nsebep=kabul\n",
            "⏸ Deploy dondurulmuş: kabul (bitiş tarihi okunamadı: 8 Aralık) (süresiz)."
            " 0123456 kurulmadı.",
        ),
    ],
)
def test_a_freeze_holds_through_its_last_day(pi: Pi, content: str, message: str) -> None:
    pi.paths.dondur.parent.mkdir()
    pi.paths.dondur.write_text(content, encoding="utf-8")

    frozen = kur.freeze(pi.paths, TODAY)

    assert frozen is not None
    assert kur.frozen_message(frozen, SHA) == message


def test_a_freeze_ends_after_its_last_day_and_no_file_means_no_freeze(pi: Pi) -> None:
    assert kur.freeze(pi.paths, TODAY) is None
    pi.paths.dondur.parent.mkdir()
    pi.paths.dondur.write_text("bitis=2026-11-24\nsebep=eski\n", encoding="utf-8")

    assert kur.freeze(pi.paths, TODAY) is None


def test_a_child_of_the_installed_commit_on_main_passes(pi: Pi) -> None:
    installed = kur.installed(pi.paths)
    child = pi.commit({"docs/DESIGN.md": "yeni tasarım\n"})

    assert kur.verify(pi.paths, child) == installed


def test_the_installed_commit_is_left_alone(pi: Pi) -> None:
    installed = kur.installed(pi.paths)
    assert installed is not None

    result = _verify_fails(pi, installed)

    assert (result.kod, result.mesaj) == (
        kur.Kod.TAMAM,
        f"{installed[:7]} zaten kurulu; bir şey yapılmadı.",
    )


def test_an_unknown_commit_a_side_branch_and_going_back_are_refused(pi: Pi) -> None:
    first = kur.installed(pi.paths)
    assert first is not None
    side = pi.commit({"docs/DESIGN.md": "deneme\n"}, branch="yan")
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})

    unknown = _verify_fails(pi, SHA)
    off_main = _verify_fails(pi, side)
    pi.install(child)
    back = _verify_fails(pi, first)

    assert (unknown.kod, unknown.mesaj) == (
        kur.Kod.RET,
        "Reddedildi: 0123456 GitHub'da bulunamadı.",
    )
    assert (off_main.kod, off_main.mesaj) == (kur.Kod.RET, f"Reddedildi: {side[:7]} `main`'de yok.")
    assert back.kod == kur.Kod.RET
    assert back.mesaj == (
        f"Reddedildi: kurulu sürüm ({child[:7]}) {first[:7]} commit'inin atası değil; "
        "geriye dönüş yapılmaz."
    )


def test_an_unreachable_github_changes_nothing(pi: Pi) -> None:
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.origin.rename(pi.origin.with_name("kayip"))

    result = _verify_fails(pi, child)

    assert result.kod == kur.Kod.BASARISIZ
    assert result.mesaj.startswith("❌ GitHub'dan çekilemedi: ")
    assert result.mesaj.endswith(". Canlı sürüm değişmedi.")


def test_without_a_current_release_a_manual_install_is_needed(pi: Pi) -> None:
    pi.paths.current.unlink()

    result = _verify_fails(pi, SHA)

    assert result.kod == kur.Kod.ELLE_KURULUM


def test_a_release_is_prepared_beside_the_live_one(pi: Pi) -> None:
    installed = kur.installed(pi.paths)
    assert installed is not None
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    kur.verify(pi.paths, child)

    release = kur.prepare(pi.paths, child, installed)

    assert release == pi.paths.surumler / child
    assert (release / "docs/DESIGN.md").read_text(encoding="utf-8") == "yeni\n"
    assert (release / ".venv/bin").is_dir()
    assert kur.installed(pi.paths) == installed
    assert pi.uv_log.read_text(encoding="utf-8").splitlines() == [
        f"{os.path.realpath(release)}|sync --locked --no-dev|{pi.paths.python}|{pi.paths.uv_cache}"
    ]


def test_a_failed_uv_sync_removes_the_release_and_leaves_the_live_one(
    pi: Pi, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = kur.installed(pi.paths)
    assert installed is not None
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    kur.verify(pi.paths, child)
    monkeypatch.setenv("FAKE_UV_FAIL", "1")

    with pytest.raises(kur.Durdur) as stopped:
        kur.prepare(pi.paths, child, installed)

    assert stopped.value.sonuc.kod == kur.Kod.BASARISIZ
    assert stopped.value.sonuc.mesaj == (
        "❌ Hazırlık başarısız (uv sync): uv: uv.lock güncel değil. Canlı sürüm değişmedi."
    )
    assert not (pi.paths.surumler / child).exists()
    assert str(pi.paths.surumler / child) not in pi.worktrees()
    assert kur.installed(pi.paths) == installed


def test_a_leftover_directory_from_an_earlier_attempt_is_replaced(pi: Pi) -> None:
    installed = kur.installed(pi.paths)
    assert installed is not None
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    kur.verify(pi.paths, child)
    leftover = pi.paths.surumler / child
    leftover.mkdir()
    (leftover / "yarim").write_text("önceki deneme", encoding="utf-8")

    release = kur.prepare(pi.paths, child, installed)

    assert not (release / "yarim").exists()
    assert (release / "docs/DESIGN.md").exists()


def _reasons(pi: Pi, files: dict[str, str | None]) -> list[str]:
    installed = kur.installed(pi.paths)
    assert installed is not None
    child = pi.commit(files)
    kur.verify(pi.paths, child)
    release = kur.prepare(pi.paths, child, installed)
    return kur.manual_reasons(pi.paths, release, pi.paths.surumler / installed)


def test_a_change_without_units_scripts_or_migrations_installs_by_itself(pi: Pi) -> None:
    (pi.paths.systemd / "timers.target.wants").mkdir()
    (pi.paths.systemd / "timers.target.wants" / "finans-backup.timer").symlink_to(
        pi.paths.systemd / "finans-backup.timer"
    )
    (pi.paths.systemd / "finans-eski.timer").symlink_to(os.devnull)
    (pi.paths.systemd / "ssh.service.d").mkdir()
    (pi.paths.systemd / "ssh.service.d" / "yerel.conf").write_text("x", encoding="utf-8")

    assert _reasons(pi, {"docs/DESIGN.md": "yeni\n", "src/finans/x.py": "x = 1\n"}) == []


@pytest.mark.parametrize(
    ("files", "reasons"),
    [
        (
            {"deploy/systemd/finans-backup.timer": "[Timer]\nOnCalendar=*-*-* 04:00\n"},
            ["birim dosyası değişti (finans-backup.timer)"],
        ),
        (
            {"deploy/systemd/finans-deploy.path": "[Path]\n"},
            ["birim dosyası değişti (finans-deploy.path)"],
        ),
        (
            {"deploy/systemd/finans-backup.timer": None},
            ["birim dosyası değişti (finans-backup.timer)"],
        ),
        (
            {"deploy/systemd/finans-web.service.d/profil.conf": "[Service]\n"},
            ["birim dosyası değişti (finans-web.service.d/profil.conf)"],
        ),
        ({"deploy/ci/kur.py": "# kur 2\n"}, ["deploy betiği değişti (kur)"]),
        (
            {"src/finans/adapters/sqlite/migrations/0002_yeni.sql": "SELECT 1;\n"},
            ["yeni migration (0002_yeni.sql)"],
        ),
        (
            {"src/finans/adapters/sqlite/migrations/0001_init.sql": "CREATE TABLE u (y);\n"},
            ["uygulanmış migration değişti (0001_init.sql)"],
        ),
    ],
)
def test_units_scripts_and_migrations_need_a_manual_install(
    pi: Pi, files: dict[str, str | None], reasons: list[str]
) -> None:
    assert _reasons(pi, files) == reasons


def test_every_reason_is_named_in_one_message(pi: Pi) -> None:
    reasons = _reasons(
        pi,
        {
            "deploy/systemd/finans-backup.timer": "[Timer]\n",
            "deploy/ci/istek.py": "# istek 2\n",
            "src/finans/adapters/sqlite/migrations/0002_yeni.sql": "SELECT 1;\n",
        },
    )

    assert kur.manual_message(reasons, SHA) == (
        "⚠ Elle kurulum gerekiyor: birim dosyası değişti (finans-backup.timer); "
        "deploy betiği değişti (istek); yeni migration (0002_yeni.sql). "
        "0123456 kurulmadı; hazırlanan dizin silindi."
    )


def test_the_result_is_written_whole_and_readable_by_the_request_side(pi: Pi) -> None:
    result = kur.Sonuc(kur.Kod.TAMAM, "✅ güncellendi", SHA, "a" * 40)
    now = datetime(2026, 12, 16, 11, 0, tzinfo=kur.ISTANBUL)

    target = kur.write_result(pi.paths, IDENT, result, now)

    assert target == pi.paths.sonuc / f"{IDENT}.json"
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "sha": SHA,
        "kod": 0,
        "mesaj": "✅ güncellendi",
        "onceki": "a" * 40,
        "zaman": "2026-12-16T11:00:00+03:00",
    }
    assert stat.S_IMODE(target.stat().st_mode) == kur.RESULT_MODE
    assert [p.name for p in pi.paths.sonuc.iterdir()] == [f"{IDENT}.json"]
    paths = istek.Yollar(pi.paths.istek, pi.paths.sonuc, pi.paths.sonuc / "kur.lock")
    assert istek.wait_result(paths, IDENT) == (istek.Kod.TAMAM, "✅ güncellendi")


def test_today_is_counted_in_istanbul() -> None:
    late = datetime(2026, 11, 25, 22, 30, tzinfo=UTC)

    assert kur.today_in_istanbul(lambda: late) == date(2026, 11, 26)


def test_last_line_of_an_empty_error_still_says_something() -> None:
    assert kur.last_line("\n  \n") == "ayrıntı yok"
    assert kur.last_line("uyarı\nhata: kayıp\n") == "hata: kayıp"


def test_a_path_that_is_not_a_release_link_is_not_an_installed_version(
    pi: Pi, tmp_path: Path
) -> None:
    paths = replace(pi.paths, current=tmp_path / "baska-current")
    paths.current.symlink_to("baska-bir-yer")

    assert kur.installed(paths) is None


def test_a_release_directory_that_cannot_be_made_changes_nothing(pi: Pi) -> None:
    installed = kur.installed(pi.paths)
    assert installed is not None
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    kur.verify(pi.paths, child)
    pi.paths.surumler.chmod(0o500)
    try:
        with pytest.raises(kur.Durdur) as stopped:
            kur.prepare(pi.paths, child, installed)
    finally:
        pi.paths.surumler.chmod(0o755)

    assert stopped.value.sonuc.kod == kur.Kod.BASARISIZ
    assert stopped.value.sonuc.mesaj.startswith("❌ Sürüm dizini hazırlanamadı: ")
    assert kur.installed(pi.paths) == installed


def test_without_installed_units_every_unit_needs_a_manual_install(pi: Pi) -> None:
    shutil.rmtree(pi.paths.systemd)

    reasons = _reasons(pi, {"docs/DESIGN.md": "yeni\n"})

    assert reasons == [
        "birim dosyası değişti (finans-backup.timer, finans-web.service, "
        "finans-web.service.d/profil.conf)"
    ]
