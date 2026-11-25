"""finans-guncelle'nin ilk adımları (K-140): argümanlar, kilit, SHA doğrulama ve elle kurulum
kuralları. Git gerçektir; git'i yalnız `finans` kullanıcısı çalıştırır."""

import os
from pathlib import Path

import pytest

import guncelle
from tests.deploy_guncelle.conftest import Pi

SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([SHA], guncelle.Istek(SHA, geri=False, paket=False)),
        ([SHA, "--geri"], guncelle.Istek(SHA, geri=True, paket=False)),
        ([SHA, "--paket", "-"], guncelle.Istek(SHA, geri=False, paket=True)),
        ([SHA, "--paket", "-", "--geri"], guncelle.Istek(SHA, geri=True, paket=True)),
    ],
)
def test_the_accepted_requests(argv: list[str], expected: guncelle.Istek) -> None:
    assert guncelle.parse_args(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [
        [],
        [SHA.upper()],
        [SHA[:39]],
        [f"{SHA}0"],
        [f" {SHA}"],
        [f"{SHA}\n"],
        [f"{SHA};id"],
        ["$(id)"],
        [SHA, "--geri", "--geri"],
        [SHA, "--paket"],
        [SHA, "--paket", "/etc/shadow"],
        [SHA, "--paket", "-", "--paket", "-"],
        [SHA, "--force"],
        [SHA, SHA],
    ],
)
def test_anything_else_is_refused(argv: list[str]) -> None:
    assert guncelle.parse_args(argv) is None


def test_a_second_run_waits_for_nothing_and_is_busy(pi: Pi) -> None:
    with guncelle.held(pi.paths), pytest.raises(guncelle.Durdur) as caught:  # noqa: SIM117
        with guncelle.held(pi.paths):
            pass

    assert caught.value.sonuc.kod == guncelle.Kod.MESGUL


def test_the_lock_does_not_follow_a_symlink(pi: Pi, tmp_path: Path) -> None:
    target = tmp_path / "baska-dosya"
    pi.paths.kilit.symlink_to(target)

    with pytest.raises(guncelle.Durdur) as caught, guncelle.held(pi.paths):
        pass

    assert caught.value.sonuc.kod == guncelle.Kod.BASARISIZ
    assert not target.exists()


def _verify(pi: Pi, sha: str, *, geri: bool = False) -> str:
    return guncelle.verify(pi.paths, guncelle.Istek(sha, geri=geri, paket=False))


def _refused(pi: Pi, sha: str, *, geri: bool = False) -> guncelle.Sonuc:
    with pytest.raises(guncelle.Durdur) as caught:
        _verify(pi, sha, geri=geri)
    return caught.value.sonuc


def test_the_installed_commit_is_not_installed_again_and_nothing_is_fetched(pi: Pi) -> None:
    result = _refused(pi, pi.head())

    assert result == guncelle.Sonuc(
        guncelle.Kod.TAMAM, f"{pi.head()[:7]} zaten kurulu; bir şey yapılmadı."
    )
    assert pi.users() == ["finans git"]


def test_a_commit_on_main_ahead_of_the_installed_one_passes(pi: Pi) -> None:
    installed = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    assert _verify(pi, new) == installed


def test_an_unknown_commit_is_refused(pi: Pi) -> None:
    assert _refused(pi, SHA) == guncelle.Sonuc(
        guncelle.Kod.RET, "⛔ Reddedildi: 0123456 bulunamadı."
    )


def test_a_commit_off_main_is_refused(pi: Pi) -> None:
    side = pi.commit({"docs/DESIGN.md": "yan dal\n"}, branch="deneme")

    assert _refused(pi, side) == guncelle.Sonuc(
        guncelle.Kod.RET, f"⛔ Reddedildi: {side[:7]} main'de yok."
    )


def test_going_back_is_refused_without_geri_and_allowed_with_it(pi: Pi) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.install(new)

    assert _refused(pi, old).kod == guncelle.Kod.RET
    assert "geriye dönüş için --geri" in _refused(pi, old).mesaj
    assert _verify(pi, old, geri=True) == new


def test_a_failed_fetch_changes_nothing(pi: Pi) -> None:
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.origin.rename(pi.origin.with_name("tasindi"))

    result = _refused(pi, new)

    assert result.kod == guncelle.Kod.BASARISIZ
    assert result.mesaj.startswith("❌ GitHub'dan çekilemedi: ")
    assert result.mesaj.endswith(". Hiçbir şey değişmedi.")


def test_git_runs_only_as_the_finans_user(pi: Pi) -> None:
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    _verify(pi, new)
    guncelle.manual_reasons(pi.paths, new, pi.head(), geri=False)

    assert pi.users()
    assert set(pi.users()) == {"finans git"}


def _reasons(pi: Pi, sha: str, *, geri: bool = False) -> list[str]:
    pi.fetch()
    return guncelle.manual_reasons(pi.paths, sha, pi.head(), geri=geri)


def test_identical_copies_need_no_manual_install(pi: Pi) -> None:
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    assert _reasons(pi, new) == []


def test_changed_new_and_removed_units_need_manual_install(pi: Pi) -> None:
    new = pi.commit(
        {
            "deploy/systemd/finans-web.service": "[Service]\nExecStart=/bin/true\n",
            "deploy/systemd/finans-yeni.timer": "[Timer]\nOnCalendar=daily\n",
            "deploy/systemd/finans-backup.timer": None,
            "deploy/systemd/finans-web.service.d/profil.conf": "[Service]\n",
        }
    )

    assert _reasons(pi, new) == [
        "birim dosyası farklı (finans-backup.timer, finans-web.service, "
        "finans-web.service.d/profil.conf, finans-yeni.timer)"
    ]


def test_other_services_in_the_unit_directory_are_ignored(pi: Pi) -> None:
    (pi.paths.systemd / "baska.service").write_text("[Service]\n", encoding="utf-8")
    wants = pi.paths.systemd / "timers.target.wants"
    wants.mkdir()
    (wants / "finans-backup.timer").symlink_to(pi.paths.systemd / "finans-backup.timer")
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    assert _reasons(pi, new) == []


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("deploy/ft-finans", "wrapper kopyası farklı (ft-finans)"),
        ("deploy/ft-sanal", "wrapper kopyası farklı (ft-sanal)"),
        ("deploy/guncelle.py", "deploy betiği farklı (finans-guncelle)"),
    ],
)
def test_a_changed_wrapper_or_this_script_needs_manual_install(
    pi: Pi, source: str, reason: str
) -> None:
    new = pi.commit({source: "#!/bin/sh\n# yeni\n"})

    assert _reasons(pi, new) == [reason]


def test_a_stale_installed_copy_is_found_without_a_change_in_the_commit(pi: Pi) -> None:
    (pi.paths.betikler / "ft-finans").write_text("#!/bin/sh\n# elle değişti\n", encoding="utf-8")
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    assert _reasons(pi, new) == ["wrapper kopyası farklı (ft-finans)"]


def test_going_back_past_a_migration_needs_a_restore_first(pi: Pi) -> None:
    old = pi.head()
    new = pi.commit({f"{guncelle.MIGRATIONS}/0002_yeni.sql": "CREATE TABLE u (y TEXT);\n"})
    pi.install(new)

    [reason] = _reasons(pi, old, geri=True)

    assert reason.startswith("geri dönüş şemayı geri almaz (0002_yeni.sql kurulu ama hedefte yok)")
    assert "K-55" in reason


def test_going_back_without_a_lost_migration_needs_nothing(pi: Pi) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.install(new)

    assert _reasons(pi, old, geri=True) == []


def test_the_manual_message_lists_every_reason_and_says_nothing_changed() -> None:
    message = guncelle.manual_message(["birim dosyası farklı (a)", "wrapper kopyası farklı (b)"])

    assert message == (
        "⚠ Elle kurulum gerekiyor: birim dosyası farklı (a); wrapper kopyası farklı (b). Hiçbir "
        "şey değişmedi; kopyalar yenilenince yeniden çalıştır (DESIGN Kurulum adım 6, 7 ve 12)."
    )


def test_production_paths_never_point_into_the_finans_owned_tree() -> None:
    """Root'un çalıştırdığı ya da karşılaştırdığı kopyalar `/opt/finans` dışındadır."""
    paths = guncelle.URETIM

    for path in (paths.systemd, paths.betikler, paths.betik, paths.kilit, paths.finans_env):
        assert not path.is_relative_to(paths.repo)
    assert paths.betik.parent == paths.betikler
    assert paths.kullanici == "finans"
    assert "PATH" in paths.ortam
    assert os.pathsep.join(["/usr/local/bin", "/usr/bin"]) in paths.ortam["PATH"]
