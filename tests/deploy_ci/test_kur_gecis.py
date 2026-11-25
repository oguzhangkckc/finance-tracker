"""Deploy çalıştırıcısının geçiş kısmı (K-134, K-135): zamanlayıcı penceresi, iş kilitleri, atomik
geçiş, web'in yeniden başlatılması, ayrı birimdeki sağlık denetimi, geri dönüş ve sürüm temizliği.
Saat ve systemd sahtedir; git gerçektir."""

import fcntl
import json
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pytest

import istek
import kur
from tests.deploy_ci.conftest import LOGIN, NOW, Pi, Systemd, Web

TODAY = date(2026, 12, 16)
IDENT = "c" * 32
FAILED_DOCTOR = "✓ SQLite: 3.53\n✗ Web yazma şifresi: scrypt özeti değil\n✗ Yedek: alıcı yok\n"


def _recorder(seen: list[str]) -> Callable[[str], str | None]:
    def notify(text: str) -> str | None:
        seen.append(text)
        return None

    return notify


def _env(systemd: Systemd, login: str = LOGIN) -> kur.Ortam:
    return kur.Ortam(kur.run, systemd.sleep, systemd.now, TODAY, login)


@contextmanager
def _held(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        yield
    finally:
        os.close(descriptor)


@pytest.mark.usefixtures("pi")
def test_a_timer_due_within_fifteen_minutes_is_found(systemd: Systemd) -> None:
    systemd.timers_due(
        ("finans-backup.timer", NOW + 3600),
        ("finans-sanal-sync-prices.timer", NOW + 600),
        ("finans-sync-cpi.timer", NOW + 300),
    )

    assert kur.upcoming_timer(kur.run, NOW) == ("finans-sync-cpi.timer", NOW + 300)


@pytest.mark.usefixtures("pi")
def test_no_timer_inside_the_window_lets_the_deploy_go_on(systemd: Systemd) -> None:
    systemd.timers_due(("finans-backup.timer", NOW + 16 * 60), ("finans-payday.timer", NOW - 5))
    systemd.timers.write_text(
        systemd.timers.read_text(encoding="utf-8")
        + "\nId=finans-yeni.timer\nNextElapseUSecRealtime=n/a\n",
        encoding="utf-8",
    )

    assert kur.upcoming_timer(kur.run, NOW) is None


@pytest.mark.usefixtures("systemd")
def test_unreadable_timers_stop_the_deploy(tmp_path: Path) -> None:
    (tmp_path / "timers.fail").write_text("x", encoding="utf-8")

    assert kur.upcoming_timer(kur.run, NOW) == ("zamanlayıcılar okunamadı", NOW)


def test_every_scheduled_job_has_a_lock_and_existing_locks_are_kept(pi: Pi) -> None:
    (pi.paths.systemd / "finans-sanal-payday.timer").write_text("[Timer]\n", encoding="utf-8")
    (pi.paths.kilitler[0] / "sync-prices.lock").write_bytes(b"")
    real, sanal = pi.paths.kilitler

    assert kur.lock_files(pi.paths) == [
        real / "backup.lock",
        sanal / "payday.lock",
        real / "sync-prices.lock",
    ]


def test_the_locks_are_held_for_the_switch_and_released_after(pi: Pi, systemd: Systemd) -> None:
    files = kur.lock_files(pi.paths)

    with kur.job_locks(files, wait=60, sleep=systemd.sleep, now=systemd.now) as busy:
        assert busy == []
        assert systemd._locked()

    assert not systemd._locked()


def test_a_running_job_is_waited_for_and_named_when_it_does_not_finish(
    pi: Pi, systemd: Systemd
) -> None:
    files = kur.lock_files(pi.paths)

    with (
        _held(pi.paths.kilitler[0] / "backup.lock"),
        kur.job_locks(files, wait=600, sleep=systemd.sleep, now=systemd.now) as busy,
    ):
        assert busy == ["backup"]

    assert systemd.clock == NOW + 600


def test_the_switch_points_current_to_the_new_release_in_one_step(pi: Pi) -> None:
    first = kur.installed(pi.paths)
    assert first is not None
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.install(child)

    kur.switch(pi.paths, first)

    assert os.readlink(pi.paths.current) == f"releases/{first}"
    assert sorted(p.name for p in pi.paths.current.parent.iterdir()) == [
        "current",
        "releases",
        "repo.git",
    ]


def test_the_web_restart_waits_for_a_new_main_process(pi: Pi, systemd: Systemd) -> None:
    assert kur.restart_web(pi.paths, kur.run, sleep=systemd.sleep, now=systemd.now) is None
    assert systemd.pid == 101
    assert not pi.paths.web_istek.exists()


def test_a_web_that_does_not_come_back_is_reported(pi: Pi, systemd: Systemd) -> None:
    systemd.web_restarts = False

    problem = kur.restart_web(pi.paths, kur.run, sleep=systemd.sleep, now=systemd.now)

    assert problem == "web 60 saniyede yeniden başlamadı"


def test_the_health_unit_result_and_its_failing_lines_are_read(pi: Pi, systemd: Systemd) -> None:
    systemd.doctor_results = ["success", "exit-code"]
    ok = kur.run_health_unit(pi.paths, sleep=systemd.sleep, now=systemd.now)
    systemd.doctor_output = FAILED_DOCTOR

    failed = kur.run_health_unit(pi.paths, sleep=systemd.sleep, now=systemd.now)

    assert ok is None
    assert failed == "doctor: ✗ Web yazma şifresi: scrypt özeti değil; ✗ Yedek: alıcı yok"


def test_a_health_unit_that_never_answers_fails_the_check(pi: Pi) -> None:
    clock = iter(range(0, 1000, 2))

    problem = kur.run_health_unit(pi.paths, sleep=lambda _s: None, now=lambda: float(next(clock)))

    assert problem == (
        "sağlık birimi 3 dakikada sonuç vermedi (`journalctl -u finans-deploy-saglik.service`)"
    )


def test_both_profile_pages_must_answer_with_the_allowed_login(
    pi: Pi, systemd: Systemd, web: Web
) -> None:
    assert kur.check_pages(pi.paths, LOGIN, sleep=systemd.sleep, now=systemd.now) is None
    assert web.logins == [LOGIN, LOGIN]

    web.statuses["/sanal/"] = 500
    broken = kur.check_pages(pi.paths, LOGIN, sleep=systemd.sleep, now=systemd.now)
    wrong = kur.check_pages(pi.paths, "baska@example.com", sleep=systemd.sleep, now=systemd.now)
    empty = kur.check_pages(pi.paths, "", sleep=systemd.sleep, now=systemd.now)

    assert broken == "web /sanal/ için 500 döndü"
    assert wrong == "web /gercek/ için 403 döndü"
    assert empty == "FT_WEB_ALLOWED_LOGIN tanımlı değil; web denetlenemedi"


def test_no_web_socket_is_no_answer(pi: Pi, systemd: Systemd) -> None:
    problem = kur.check_pages(pi.paths, LOGIN, sleep=systemd.sleep, now=systemd.now)

    assert problem == "web /gercek/ için yanıt yok döndü"


@pytest.mark.usefixtures("web")
def test_a_healthy_deploy_switches_under_the_locks_and_says_what_was_installed(
    pi: Pi, systemd: Systemd
) -> None:
    previous = kur.installed(pi.paths)
    assert previous is not None
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})

    result = kur.deploy(pi.paths, child, _env(systemd))

    assert result == kur.Sonuc(
        kur.Kod.TAMAM,
        f"✅ finans güncellendi: {child[:7]} değişiklik (main) (önceki {previous[:7]}).",
        child,
        previous,
    )
    assert kur.installed(pi.paths) == child
    assert systemd.events == [("web", child, True), ("saglik", child, False)]


@pytest.mark.usefixtures("web")
def test_a_failed_health_check_goes_back_and_names_the_reason(pi: Pi, systemd: Systemd) -> None:
    previous = kur.installed(pi.paths)
    assert previous is not None
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    systemd.doctor_results = ["exit-code", "success"]
    systemd.doctor_output = FAILED_DOCTOR

    result = kur.deploy(pi.paths, child, _env(systemd))

    assert result.kod == kur.Kod.BASARISIZ
    assert result.mesaj == (
        "❌ finans güncellemesi başarısız: doctor: ✗ Web yazma şifresi: scrypt özeti değil; "
        f"✗ Yedek: alıcı yok. {previous[:7]} sürümüne geri dönüldü."
    )
    assert kur.installed(pi.paths) == previous
    assert [event[:2] for event in systemd.events] == [
        ("web", child),
        ("saglik", child),
        ("web", previous),
        ("saglik", previous),
    ]


@pytest.mark.usefixtures("web")
def test_a_web_that_does_not_restart_goes_back_and_asks_for_a_person(
    pi: Pi, systemd: Systemd
) -> None:
    previous = kur.installed(pi.paths)
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    systemd.web_restarts = False

    result = kur.deploy(pi.paths, child, _env(systemd))

    assert result.kod == kur.Kod.BASARISIZ
    assert result.mesaj == (
        "🚨 Geri dönüş başarısız, elle müdahale gerekiyor: web 60 saniyede yeniden başlamadı; "
        "geri dönüşte: web 60 saniyede yeniden başlamadı."
    )
    assert kur.installed(pi.paths) == previous


@pytest.mark.usefixtures("web")
def test_a_failed_way_back_asks_for_a_person(pi: Pi, systemd: Systemd) -> None:
    previous = kur.installed(pi.paths)
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    systemd.doctor_results = ["exit-code", "exit-code"]

    result = kur.deploy(pi.paths, child, _env(systemd))

    assert result.mesaj == (
        "🚨 Geri dönüş başarısız, elle müdahale gerekiyor: doctor: başarısız; "
        "geri dönüşte: doctor: başarısız."
    )
    assert kur.installed(pi.paths) == previous


def test_a_timer_in_the_window_installs_nothing(pi: Pi, systemd: Systemd) -> None:
    previous = kur.installed(pi.paths)
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    systemd.timers_due(("finans-sanal-sync-prices.timer", NOW + 600))

    result = kur.deploy(pi.paths, child, _env(systemd))

    at = datetime.fromtimestamp(NOW + 600, kur.ISTANBUL).strftime("%H:%M")
    assert result.kod == kur.Kod.MESGUL
    assert result.mesaj == (
        f"⏳ Pencere dışı: finans-sanal-sync-prices.timer {at} (İstanbul) çalışacak; "
        "deploy yapılmadı, sonra yeniden çalıştır."
    )
    assert kur.installed(pi.paths) == previous
    assert not (pi.paths.surumler / child).exists()
    assert systemd.events == []


def test_a_job_that_keeps_running_installs_nothing(pi: Pi, systemd: Systemd) -> None:
    previous = kur.installed(pi.paths)
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})

    with _held(pi.paths.kilitler[0] / "backup.lock"):
        result = kur.deploy(pi.paths, child, _env(systemd))

    assert (result.kod, result.mesaj) == (
        kur.Kod.MESGUL,
        "⏳ Çalışan iş 10 dakikada bitmedi (backup); deploy yapılmadı, yeniden çalıştır.",
    )
    assert kur.installed(pi.paths) == previous
    assert not (pi.paths.surumler / child).exists()


def test_a_manual_change_or_a_freeze_switches_nothing(pi: Pi, systemd: Systemd) -> None:
    previous = kur.installed(pi.paths)
    child = pi.commit({"deploy/systemd/finans-backup.timer": "[Timer]\n"})

    manual = kur.deploy(pi.paths, child, _env(systemd))
    pi.paths.dondur.parent.mkdir()
    pi.paths.dondur.write_text("sebep=bakım\n", encoding="utf-8")
    frozen = kur.deploy(pi.paths, child, _env(systemd))

    assert manual.kod == kur.Kod.ELLE_KURULUM
    assert not (pi.paths.surumler / child).exists()
    assert (frozen.kod, frozen.mesaj) == (
        kur.Kod.TAMAM,
        f"⏸ Deploy dondurulmuş: bakım (süresiz). {child[:7]} kurulmadı.",
    )
    assert kur.installed(pi.paths) == previous
    assert systemd.events == []


def test_only_the_last_three_releases_and_the_ones_in_use_are_kept(pi: Pi) -> None:
    oldest = kur.installed(pi.paths)
    assert oldest is not None
    os.utime(pi.paths.surumler / oldest, (NOW - 10, NOW - 10))
    shas = []
    for number in range(4):
        sha = pi.commit({"docs/DESIGN.md": f"sürüm {number}\n"})
        pi.install(sha)
        os.utime(pi.paths.surumler / sha, (NOW + number, NOW + number))
        shas.append(sha)

    kur.prune(pi.paths, {shas[0]})

    assert sorted(p.name for p in pi.paths.surumler.iterdir()) == sorted(shas)


@pytest.mark.usefixtures("web")
def test_main_runs_one_request_writes_its_result_and_notifies(pi: Pi, systemd: Systemd) -> None:
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.paths.istek.write_text(f"{child}\n{IDENT}\n", encoding="ascii")
    seen: list[str] = []
    busy_during: list[bool] = []
    request_side = istek.Yollar(pi.paths.istek, pi.paths.sonuc, pi.paths.sonuc / "kur.lock")

    def sleep(seconds: float) -> None:
        busy_during.append(istek.busy(request_side))
        systemd.sleep(seconds)

    env = kur.Ortam(kur.run, sleep, systemd.now, TODAY, LOGIN)
    code = kur.main(pi.paths, env, _recorder(seen), environ={})

    data = json.loads((pi.paths.sonuc / f"{IDENT}.json").read_text(encoding="utf-8"))
    assert code == 0
    assert (data["kod"], data["sha"]) == (0, child)
    assert data["mesaj"].startswith(f"✅ finans güncellendi: {child[:7]}")
    assert seen == [data["mesaj"]]
    assert busy_during
    assert all(busy_during)
    assert not istek.busy(request_side)
    lock = pi.paths.sonuc / "kur.lock"
    assert stat.S_IMODE(lock.stat().st_mode) == kur.RESULT_MODE


def test_main_without_a_request_does_nothing(pi: Pi, systemd: Systemd) -> None:
    seen: list[str] = []

    assert kur.main(pi.paths, _env(systemd), _recorder(seen), environ={}) == 0
    assert seen == []
    assert [p.name for p in pi.paths.sonuc.iterdir()] == ["kur.lock"]


def test_main_writes_a_refusal_as_a_result(pi: Pi, systemd: Systemd) -> None:
    pi.paths.istek.write_text(f"{'0' * 40}\n{IDENT}\n", encoding="ascii")
    seen: list[str] = []

    code = kur.main(pi.paths, _env(systemd), _recorder(seen), environ={})

    assert code == kur.Kod.RET
    assert seen == ["⛔ Deploy reddedildi: 0000000 GitHub'da bulunamadı."]


def test_a_switch_that_cannot_be_made_is_reported_with_the_way_back(
    pi: Pi, systemd: Systemd, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = kur.installed(pi.paths)
    child = pi.commit({"docs/DESIGN.md": "yeni\n"})

    def denied(_paths: kur.Yollar, _sha: str) -> None:
        raise PermissionError

    monkeypatch.setattr(kur, "switch", denied)

    result = kur.deploy(pi.paths, child, _env(systemd))

    assert result.mesaj == (
        "🚨 Geri dönüş başarısız, elle müdahale gerekiyor: geçiş yapılamadı (PermissionError); "
        "geri dönüşte: geri geçiş yapılamadı (PermissionError)."
    )
    assert kur.installed(pi.paths) == previous


def test_a_failed_doctor_without_readable_output_still_fails(pi: Pi, systemd: Systemd) -> None:
    systemd.doctor_results = ["exit-code"]
    original = systemd.sleep

    def sleep(seconds: float) -> None:
        original(seconds)
        (pi.paths.saglik / "doctor.txt").unlink(missing_ok=True)

    problem = kur.run_health_unit(pi.paths, sleep=sleep, now=systemd.now)

    assert problem == "doctor: başarısız"
