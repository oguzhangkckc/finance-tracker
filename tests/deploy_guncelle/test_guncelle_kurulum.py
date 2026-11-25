"""finans-guncelle'nin kurulum adımları (K-140): iş bekleme, kod ve uv, ön yüz paketi, migration
öncesi yedek denetimi, web'in yeniden başlatılması ve sağlık. Çıktı herkese açık CI günlüğüne
gider."""

import io
import itertools
import re
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

import guncelle
from tests.deploy_guncelle.conftest import Pi, Saat

REPO = Path(__file__).resolve().parents[2]
MIGRATION = f"{guncelle.MIGRATIONS}/0002_yeni.sql"


def _main(pi: Pi, ortam: guncelle.Ortam, *argv: str, package: bytes | None = None) -> int:
    stdin = None if package is None else io.BytesIO(package)
    return guncelle.main(list(argv), pi.paths, ortam, stdin)


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def _ft(pi: Pi, *command: str) -> list[list[str]]:
    """`ft <command>` çağıran systemd-run satırları."""
    return [call for call in pi.calls("systemd-run") if call[-len(command) :] == list(command)]


def test_a_docs_commit_is_installed_and_the_web_restarted(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    code = _main(pi, ortam, new)

    assert (code, _out(capsys)) == (0, f"✅ finans güncellendi: {new[:7]} (önceki {old[:7]}).\n")
    assert pi.head() == new
    assert pi.calls("uv") == [
        ["uv", "--directory", str(pi.paths.repo), "sync", "--locked", "--no-dev"]
    ]
    assert pi.uv_python() == [str(pi.paths.python)]
    assert ["systemctl", "restart", "finans-web.service"] in pi.calls("systemctl")
    assert len(_ft(pi, "doctor")) == 2
    assert _ft(pi, "db", "migrate") == _ft(pi, "backup", "verify") == []


def test_the_pi_stays_on_its_main_branch(pi: Pi, ortam: guncelle.Ortam) -> None:
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    _main(pi, ortam, new)

    branch = guncelle.git(pi.paths, guncelle.run, "rev-parse", "--abbrev-ref", "HEAD")
    assert guncelle.text(branch.stdout).strip() == "main"


def test_a_refused_request_runs_nothing(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _main(pi, ortam, "deploy", "x")

    assert (code, _out(capsys)) == (3, f"{guncelle.REFUSED}\n")
    assert pi.calls() == []
    assert pi.users() == []


def test_a_running_job_is_waited_for(pi: Pi, ortam: guncelle.Ortam, saat: Saat) -> None:
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.config(jobs=["finans-job@backup.service"])
    saat.after(30, lambda: pi.config(jobs=[]))

    assert _main(pi, ortam, new) == 0
    assert len([call for call in pi.calls("systemctl") if call[1] == "list-units"]) > 1


def test_a_job_that_outlasts_the_wait_leaves_everything_as_it_was(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.config(jobs=["finans-sanal-job@sync-prices.service"])

    code = _main(pi, ortam, new)

    assert code == 4
    assert "finans-sanal-job@sync-prices.service" in _out(capsys)
    assert pi.head() == old
    assert pi.calls("uv") == []


def test_a_manual_change_in_the_checkout_stops_before_anything_changes(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    (pi.paths.repo / "docs/DESIGN.md").write_text("elle\n", encoding="utf-8")

    code = _main(pi, ortam, new)

    assert code == 1
    assert "elle yapılmış değişiklik var (1 dosya)" in _out(capsys)
    assert pi.head() == old


def test_a_failed_uv_sync_returns_to_the_previous_commit(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.config(uv_fail=1)

    code = _main(pi, ortam, new)

    assert (code, _out(capsys)) == (
        1,
        "❌ Hazırlık başarısız (uv sync: error: uv.lock güncel değil). Önceki commit'e "
        f"({old[:7]}) dönüldü; web yeniden başlatılmadı.\n",
    )
    assert pi.head() == old
    assert len(pi.calls("uv")) == 2
    assert not any(call[1] == "restart" for call in pi.calls("systemctl"))


def test_a_failed_return_asks_for_manual_intervention(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    pi.config(uv_fail=2)

    assert _main(pi, ortam, new) == 1
    assert _out(capsys).startswith("🚨 Hazırlık başarısız (uv sync: ")


def _tar(*members: tuple[tarfile.TarInfo, bytes | None]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for info, data in members:
            if data is not None:
                info.size = len(data)
            archive.addfile(info, None if data is None else io.BytesIO(data))
    return buffer.getvalue()


def _file(name: str, data: bytes) -> tuple[tarfile.TarInfo, bytes]:
    return tarfile.TarInfo(name), data


def _special(name: str, kind: bytes, link: str = "") -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    return info, None


GOOD = _tar(_file("./index.html", b"yeni"), _file("./assets/app.js", b"console.log(1)"))


@pytest.fixture
def old_dist(pi: Pi) -> Path:
    pi.paths.on_yuz.mkdir(parents=True)
    (pi.paths.on_yuz / "index.html").write_text("eski", encoding="utf-8")
    return pi.paths.on_yuz


def test_a_package_replaces_the_frontend(
    pi: Pi, ortam: guncelle.Ortam, old_dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    code = _main(pi, ortam, new, "--paket", "-", package=GOOD)

    assert code == 0
    assert _out(capsys) == (
        f"✅ finans güncellendi: {new[:7]} (önceki {old[:7]}); ön yüz yenilendi.\n"
    )
    assert (old_dist / "index.html").read_text(encoding="utf-8") == "yeni"
    assert (old_dist / "assets/app.js").exists()
    assert sorted(path.name for path in old_dist.parent.iterdir()) == ["dist"]
    assert set(pi.users()) == {"finans git", "finans uv", f"finans {pi.paths.sistem_python}"}


@pytest.mark.parametrize(
    "package",
    [
        pytest.param(_tar(_file("./index.html", b"x"), _file("../kacis.txt", b"x")), id="dotdot"),
        pytest.param(_tar(_file("./index.html", b"x"), _file("/mutlak.txt", b"x")), id="mutlak"),
        pytest.param(
            _tar(_file("./index.html", b"x"), _special("./bag", tarfile.SYMTYPE, "index.html")),
            id="sembolik",
        ),
        pytest.param(
            _tar(_file("./index.html", b"x"), _special("./sabit", tarfile.LNKTYPE, "index.html")),
            id="sabit",
        ),
        pytest.param(
            _tar(_file("./index.html", b"x"), _special("./aygit", tarfile.CHRTYPE)), id="aygit"
        ),
        pytest.param(_tar(_file("./app.js", b"x")), id="index-yok"),
        pytest.param(b"tar degil", id="bozuk"),
    ],
)
def test_a_rejected_package_keeps_the_old_frontend_and_code(
    pi: Pi,
    ortam: guncelle.Ortam,
    old_dist: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    package: bytes,
) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    code = _main(pi, ortam, new, "--paket", "-", package=package)

    assert code == 1
    assert _out(capsys).startswith("❌ Hazırlık başarısız (ön yüz paketi: ")
    assert (old_dist / "index.html").read_text(encoding="utf-8") == "eski"
    assert sorted(path.name for path in old_dist.parent.iterdir()) == ["dist"]
    assert pi.head() == old
    assert not (old_dist.parent.parent / "kacis.txt").exists()
    assert not (tmp_path / "mutlak.txt").exists()


@pytest.mark.parametrize(
    ("limit", "value", "package"),
    [
        ("UNPACKED_LIMIT", 10, _tar(_file("./index.html", b"x" * 100))),
        ("MEMBER_LIMIT", 1, GOOD),
    ],
)
def test_a_package_over_the_unpacked_limits_is_rejected(
    pi: Pi,
    ortam: guncelle.Ortam,
    old_dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
    value: int,
    package: bytes,
) -> None:
    monkeypatch.setattr(guncelle, limit, value)
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    assert _main(pi, ortam, new, "--paket", "-", package=package) == 1
    assert (old_dist / "index.html").read_text(encoding="utf-8") == "eski"


def test_a_package_over_the_size_limit_is_refused_before_anything_runs(
    pi: Pi, ortam: guncelle.Ortam, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guncelle, "PACKAGE_LIMIT", 10)
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    assert _main(pi, ortam, new, "--paket", "-", package=GOOD) == 1
    assert pi.calls() == []
    assert pi.users() == []


def test_a_new_migration_runs_in_both_profiles_after_the_checks(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    old = pi.head()
    new = pi.commit({MIGRATION: "CREATE TABLE u (y TEXT);\n"})

    code = _main(pi, ortam, new)

    assert (code, _out(capsys)) == (
        0,
        f"✅ finans güncellendi: {new[:7]} (önceki {old[:7]}); migration: 0002_yeni.sql.\n",
    )
    calls = pi.calls()
    verify = [index for index, call in enumerate(calls) if call[-2:] == ["backup", "verify"]]
    migrate = [index for index, call in enumerate(calls) if call[-2:] == ["db", "migrate"]]
    uv = [index for index, call in enumerate(calls) if call[0] == "uv"]
    restart = [index for index, call in enumerate(calls) if call[1:2] == ["restart"]]
    assert len(verify) == len(migrate) == 2
    assert max(verify) < min(uv) < min(migrate) <= max(migrate) < min(restart)
    assert "Environment=FT_PROFILE=sanal" not in calls[migrate[0]]
    assert "Environment=FT_PROFILE=sanal" in calls[migrate[1]]


def _stale(pi: Pi) -> None:
    pi.backup("finans-", age=27 * 3600)


def _missing_sanal(pi: Pi) -> None:
    for path in (pi.paths.veri / "backups").glob("sanal-*"):
        path.unlink()


def _verify_fails(pi: Pi) -> None:
    pi.config(verify_exit={"gercek": 0, "sanal": 1})


@pytest.mark.parametrize(
    ("setup", "problem"),
    [
        (_stale, "gercek: son yedek 27 saat önce"),
        (_missing_sanal, "sanal: yedek yok"),
        (_verify_fails, "sanal: backup verify başarısız"),
    ],
)
def test_a_migration_without_a_fresh_verified_backup_changes_nothing(
    pi: Pi,
    ortam: guncelle.Ortam,
    capsys: pytest.CaptureFixture[str],
    setup: Callable[[Pi], None],
    problem: str,
) -> None:
    old = pi.head()
    new = pi.commit({MIGRATION: "CREATE TABLE u (y TEXT);\n"})
    setup(pi)

    code = _main(pi, ortam, new)

    out = _out(capsys)
    assert code == 1
    assert out.startswith("❌ Migration bekliyor ama gece yedeği güncel değil (")
    assert problem in out
    assert pi.head() == old
    assert pi.calls("uv") == []
    assert _ft(pi, "db", "migrate") == []


def test_a_failed_migration_does_not_restart_and_points_to_the_copy(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    old = pi.head()
    new = pi.commit({MIGRATION: "CREATE TABLE u (y TEXT);\n"})
    pi.config(migrate_exit={"gercek": 1, "sanal": 0})

    code = _main(pi, ortam, new)

    out = _out(capsys)
    assert code == 1
    assert out.startswith("❌ gercek profilinde migration başarısız (çıkış 1).")
    assert "K-55" in out
    assert f"sha {old}" in out
    assert pi.head() == new
    assert not any(call[1] == "restart" for call in pi.calls("systemctl"))


def test_with_a_port_the_health_endpoint_is_asked(pi: Pi, ortam: guncelle.Ortam) -> None:
    pi.env(FT_WEB_PORT="8123")
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    assert _main(pi, ortam, new) == 0
    assert pi.calls("curl") == [
        ["curl", "-fsS", "-o", "/dev/null", "--max-time", "5", "http://127.0.0.1:8123/api/saglik"]
    ]


def _curl_fails(pi: Pi) -> None:
    pi.env(FT_WEB_PORT="8123")
    pi.config(curl_exit=7)


def _same_process(pi: Pi) -> None:
    pi.config(web_stays=True)


def _restart_fails(pi: Pi) -> None:
    pi.config(restart_exit=1)


def _bad_port(pi: Pi) -> None:
    pi.env(FT_WEB_PORT="80; id")


@pytest.mark.parametrize(
    ("setup", "problem"),
    [
        (_curl_fails, "web 30 saniyede hazır olmadı"),
        (_same_process, "web 30 saniyede hazır olmadı"),
        (_restart_fails, "web yeniden başlatılamadı"),
        (_bad_port, "FT_WEB_PORT sayı değil"),
    ],
)
def test_an_unhealthy_web_is_reported_with_the_way_back(
    pi: Pi,
    ortam: guncelle.Ortam,
    capsys: pytest.CaptureFixture[str],
    setup: Callable[[Pi], None],
    problem: str,
) -> None:
    old = pi.head()
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})
    setup(pi)

    code = _main(pi, ortam, new)

    out = _out(capsys)
    assert code == 1
    assert out.startswith(f"❌ {new[:7]} kuruldu ama sağlık denetimi başarısız: ")
    assert problem in out
    assert f"workflow_dispatch, sha {old}, geri seçili." in out


def test_doctor_problems_are_counted_but_never_printed(
    pi: Pi, ortam: guncelle.Ortam, capsys: pytest.CaptureFixture[str]
) -> None:
    pi.config(
        doctor={
            "gercek": {
                "out": "✗ Fiyat: XHT bayat (/var/lib/finans/finans.db)\n✓ Şema\n",
                "exit": 1,
            },
            "sanal": {"out": "✓ Şema\n", "exit": 0},
        }
    )
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    code = _main(pi, ortam, new)

    out = _out(capsys)
    assert code == 1
    assert "gercek: doctor'da 1 sorun" in out
    assert "XHT" not in out
    assert "finans.db" not in out


@pytest.mark.parametrize("present", [True, False])
def test_doctor_gets_the_web_password_only_if_it_exists(
    pi: Pi, ortam: guncelle.Ortam, present: bool
) -> None:
    if present:
        (pi.paths.credstore / guncelle.WEB_PASSWORD).write_text("özet\n", encoding="utf-8")
    new = pi.commit({"docs/DESIGN.md": "yeni\n"})

    _main(pi, ortam, new)

    doctors = _ft(pi, "doctor")
    assert len(doctors) == 2
    for call in doctors:
        loaded = any(arg.startswith("LoadCredential=ft_web_password:") for arg in call)
        assert loaded is present


@pytest.mark.parametrize(("profile", "wrapper"), [("gercek", "ft-finans"), ("sanal", "ft-sanal")])
def test_the_commands_are_the_wrappers_own(profile: str, wrapper: str) -> None:
    """Betik wrapper çağırmaz, onların `systemd-run` çağrısını kendisi kurar; ikisi ayrışmasın."""
    text = (REPO / "deploy" / wrapper).read_text(encoding="utf-8")
    loop = re.search(r"^for name in ([a-z_ ]+); do$", text, re.MULTILINE)
    assert loop is not None
    command = guncelle.ft_command(guncelle.URETIM, profile, "doctor")
    properties = [value for flag, value in itertools.pairwise(command) if flag == "-p"]
    wrapper_properties = [value for value in re.findall(r"-p (\S+)", text) if '"' not in value]

    assert tuple(loop.group(1).split()) == guncelle.CREDENTIALS[profile]
    assert properties == wrapper_properties
    for option in ("--uid=finans", "--gid=finans", "--working-directory=/var/lib/finans"):
        assert option in command
        assert option in text
    assert command[-2] == "/opt/finans/.venv/bin/ft"
    assert command[-2] in text


def test_root_runs_only_fixed_commands_and_everything_else_as_finans(
    pi: Pi, ortam: guncelle.Ortam, old_dist: Path
) -> None:
    new = pi.commit({MIGRATION: "CREATE TABLE u (y TEXT);\n"})

    assert _main(pi, ortam, new, "--paket", "-", package=GOOD) == 0

    direct = {call[0] for call in pi.calls() if call[0] != "uv"}
    assert direct <= {"systemctl", "systemd-run", "curl"}
    assert {line.split(" ", 1)[0] for line in pi.users()} == {"finans"}
    ft = str(pi.paths.repo / ".venv" / "bin" / "ft")
    for call in pi.calls("systemd-run"):
        assert "--uid=finans" in call
        assert ft in call
