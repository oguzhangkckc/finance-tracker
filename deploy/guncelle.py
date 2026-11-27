#!/usr/bin/python3 -I
"""finans-guncelle: CI'nın tek SSH çağrısıyla çalıştırdığı deploy betiği (K-140).

Pi'deki root sahipli kopyası /usr/local/sbin/finans-guncelle'dir; sudoers'ta yalnız o
NOPASSWD'dir. Sistem Python'uyla (3.12) ve yalnız standart kütüphaneyle çalışır.
/opt/finans finans'ındır; root oradaki hiçbir dosyayı çalıştırmaz, git ve uv'yi
runuser -u finans ile çağırır.
"""

import fcntl
import inspect
import os
import re
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import BinaryIO, Final, Protocol


class Kod(IntEnum):
    """Betiğin ve CI işinin çıkış kodu (K-140)."""

    TAMAM = 0
    BASARISIZ = 1
    ELLE_KURULUM = 2
    RET = 3
    MESGUL = 4


SHA: Final = re.compile(r"[0-9a-f]{40}")
UNITS: Final = "deploy/systemd"
UNIT_PREFIX: Final = "finans-"
WRAPPERS: Final = {"ft-finans": "deploy/ft-finans", "ft-sanal": "deploy/ft-sanal"}
SELF: Final = "deploy/guncelle.py"
MIGRATIONS: Final = "src/finans/adapters/sqlite/migrations"
COMMAND_TIMEOUT: Final = 15 * 60
MANUAL_STEPS: Final = "DESIGN Kurulum adım 6, 7 ve 12"
WEB_UNIT: Final = "finans-web.service"
JOB_UNITS: Final = (
    "finans-job@*",
    "finans-sanal-job@*",
    "finans-refresh.service",
    "finans-sanal-refresh.service",
)
JOB_WAIT: Final = 10 * 60
WEB_WAIT: Final = 30
POLL: Final = 2
PACKAGE_LIMIT: Final = 20 * 1024 * 1024
UNPACKED_LIMIT: Final = 100 * 1024 * 1024
MEMBER_LIMIT: Final = 5000
BACKUP_AGE: Final = 26 * 3600
BACKUP_SUFFIX: Final = ".db.age"
PROFILES: Final = ("gercek", "sanal")
BACKUP_PREFIX: Final = {"gercek": "finans-", "sanal": "sanal-"}
# Wrapper'ların for name in … satırlarıyla aynı; test ikisini karşılaştırır.
CREDENTIALS: Final = {
    "gercek": (
        "ft_evds_api_key",
        "ft_telegram_bot_token",
        "ft_healthcheck_reports_url",
        "ft_healthcheck_backup_url",
    ),
    "sanal": ("ft_evds_api_key", "ft_telegram_bot_token"),
}
WEB_PASSWORD: Final = "ft_web_password"  # noqa: S105 - credential adı, değer değil
REFUSED: Final = (
    "⛔ Reddedildi: yalnız '<40 haneli küçük harfli sha> [--geri] [--paket -]' kabul edilir."
)


@dataclass(frozen=True)
class Yollar:
    repo: Path
    systemd: Path
    betikler: Path
    betik: Path
    finans_env: Path
    kilit: Path
    python: Path
    on_yuz: Path
    credstore: Path
    veri: Path
    sistem_python: str
    kullanici: str
    ortam: Mapping[str, str]


URETIM: Final = Yollar(
    repo=Path("/opt/finans"),
    systemd=Path("/etc/systemd/system"),
    betikler=Path("/usr/local/sbin"),
    betik=Path("/usr/local/sbin/finans-guncelle"),
    finans_env=Path("/etc/finans/finans.env"),
    kilit=Path("/run/finans-guncelle.lock"),
    python=Path("/opt/finans/.python"),
    on_yuz=Path("/opt/finans/frontend/dist"),
    credstore=Path("/etc/finans/credstore"),
    veri=Path("/var/lib/finans"),
    sistem_python="/usr/bin/python3",
    kullanici="finans",
    ortam={"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C.UTF-8"},
)


@dataclass(frozen=True)
class Istek:
    sha: str
    geri: bool
    paket: bool


@dataclass(frozen=True)
class Sonuc:
    kod: Kod
    mesaj: str


class Durdur(Exception):
    def __init__(self, sonuc: Sonuc) -> None:
        super().__init__(sonuc.mesaj)
        self.sonuc = sonuc


class Calistirici(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        input: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]: ...


def run(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    input: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    # Girdi verilmezse standart girdi kapatılır: SSH'den gelen paket alt süreçlere akmasın.
    if input is None:
        return subprocess.run(  # noqa: S603 - argümanlar listedir, kabuk yok
            list(args),
            env=None if env is None else dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
    return subprocess.run(  # noqa: S603 - argümanlar listedir, kabuk yok
        list(args),
        env=None if env is None else dict(env),
        input=input,
        capture_output=True,
        check=False,
        timeout=COMMAND_TIMEOUT,
    )


def text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def short(sha: str) -> str:
    return sha[:7]


def last_line(data: bytes) -> str:
    lines = [line.strip() for line in text(data).splitlines() if line.strip()]
    return lines[-1] if lines else "ayrıntı yok"


def parse_args(argv: Sequence[str]) -> Istek | None:
    """Yalnız <sha> [--geri] [--paket -]. argparse kendi kodu 2 ile çıkardı; burada 2 elle
    kurulum demektir."""
    if not argv or not SHA.fullmatch(argv[0]):
        return None
    rest = list(argv[1:])
    geri = paket = False
    while rest:
        flag = rest.pop(0)
        if flag == "--geri" and not geri:
            geri = True
        elif flag == "--paket" and not paket and rest[:1] == ["-"]:
            rest.pop(0)
            paket = True
        else:
            return None
    return Istek(argv[0], geri, paket)


@contextmanager
def held(paths: Yollar) -> Iterator[None]:
    """O_NOFOLLOW: kilit yolundaki bir sembolik bağlantı root'a başka bir dosya açtırmasın."""
    try:
        descriptor = os.open(paths.kilit, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        message = f"❌ Kilit dosyası açılamadı ({error.strerror}). Hiçbir şey değişmedi."
        raise Durdur(Sonuc(Kod.BASARISIZ, message)) from None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            message = "⏳ Başka bir deploy sürüyor; bitince yeniden çalıştır."
            raise Durdur(Sonuc(Kod.MESGUL, message)) from None
        yield
    finally:
        os.close(descriptor)


def as_user(paths: Yollar, *args: str) -> list[str]:
    return ["runuser", "-u", paths.kullanici, "--", *args]


def git(paths: Yollar, runner: Calistirici, *args: str) -> subprocess.CompletedProcess[bytes]:
    return runner(as_user(paths, "git", "-C", str(paths.repo), *args), env=paths.ortam)


def verify(paths: Yollar, istek: Istek, runner: Calistirici = run) -> str:
    """Kurulu commit'i döndürür. Hedef main'in atası olmalı; --geri yoksa kurulu commit de
    hedefin atası olmalı."""
    head = git(paths, runner, "rev-parse", "HEAD")
    if head.returncode:
        message = f"❌ Kurulu commit okunamadı: {last_line(head.stderr)}."
        raise Durdur(Sonuc(Kod.BASARISIZ, message))
    current = text(head.stdout).strip()
    if current == istek.sha:
        raise Durdur(Sonuc(Kod.TAMAM, f"{short(istek.sha)} zaten kurulu; bir şey yapılmadı."))
    # Bütün dallar çekilir: başka daldaki bir commit "bulunamadı" değil "main'de yok" diye
    # reddedilsin.
    fetched = git(
        paths,
        runner,
        "fetch",
        "--quiet",
        "--prune",
        "origin",
        "+refs/heads/*:refs/remotes/origin/*",
    )
    if fetched.returncode:
        message = f"❌ GitHub'dan çekilemedi: {last_line(fetched.stderr)}. Hiçbir şey değişmedi."
        raise Durdur(Sonuc(Kod.BASARISIZ, message))
    if git(paths, runner, "cat-file", "-e", f"{istek.sha}^{{commit}}").returncode:
        raise Durdur(Sonuc(Kod.RET, f"⛔ Reddedildi: {short(istek.sha)} bulunamadı."))
    on_main = git(
        paths, runner, "merge-base", "--is-ancestor", istek.sha, "refs/remotes/origin/main"
    )
    if on_main.returncode:
        raise Durdur(Sonuc(Kod.RET, f"⛔ Reddedildi: {short(istek.sha)} main'de yok."))
    if (
        not istek.geri
        and git(paths, runner, "merge-base", "--is-ancestor", current, istek.sha).returncode
    ):
        message = (
            f"⛔ Reddedildi: kurulu commit ({short(current)}) {short(istek.sha)} commit'inin atası "
            "değil; geriye dönüş için --geri."
        )
        raise Durdur(Sonuc(Kod.RET, message))
    return current


def _tree(paths: Yollar, runner: Calistirici, sha: str, prefix: str) -> set[str]:
    listed = git(paths, runner, "ls-tree", "-r", "--name-only", sha, "--", prefix)
    if listed.returncode:
        message = f"❌ {short(sha)} içeriği okunamadı: {last_line(listed.stderr)}."
        raise Durdur(Sonuc(Kod.BASARISIZ, message))
    return {line.removeprefix(f"{prefix}/") for line in text(listed.stdout).splitlines() if line}


def _blob(paths: Yollar, runner: Calistirici, sha: str, path: str) -> bytes | None:
    shown = git(paths, runner, "cat-file", "blob", f"{sha}:{path}")
    return None if shown.returncode else shown.stdout


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _installed_units(systemd: Path) -> set[str]:
    """Yalnız bu projenin birimleri; *.wants bağları ve diğer servisler sayılmaz."""
    if not systemd.is_dir():
        return set()
    names: set[str] = set()
    for entry in systemd.iterdir():
        if not entry.name.startswith(UNIT_PREFIX):
            continue
        if entry.is_dir():
            names.update(
                f"{entry.name}/{path.relative_to(entry)}"
                for path in entry.rglob("*")
                if path.is_file()
            )
        elif entry.is_file():
            names.add(entry.name)
    return names


def manual_reasons(
    paths: Yollar, sha: str, current: str, geri: bool, runner: Calistirici = run
) -> list[str]:
    """Kurulu birimler, wrapper kopyaları ve betiğin kendisi hedef commit'tekiyle bayt olarak aynı
    olmalı: root finans'ın yazabildiği dizinden kopyalamaz. Geri dönüş şemayı geri almaz."""
    reasons: list[str] = []
    wanted = _tree(paths, runner, sha, UNITS)
    units = sorted(
        name
        for name in wanted | _installed_units(paths.systemd)
        if (_blob(paths, runner, sha, f"{UNITS}/{name}") if name in wanted else None)
        != _read(paths.systemd / name)
    )
    if units:
        reasons.append(f"birim dosyası farklı ({', '.join(units)})")
    wrappers = [
        name
        for name, source in WRAPPERS.items()
        if _blob(paths, runner, sha, source) != _read(paths.betikler / name)
    ]
    if wrappers:
        reasons.append(f"wrapper kopyası farklı ({', '.join(wrappers)})")
    if _blob(paths, runner, sha, SELF) != _read(paths.betik):
        reasons.append(f"deploy betiği farklı ({paths.betik.name})")
    if geri:
        lost = sorted(
            _tree(paths, runner, current, MIGRATIONS) - _tree(paths, runner, sha, MIGRATIONS)
        )
        if lost:
            reasons.append(
                f"geri dönüş şemayı geri almaz ({', '.join(lost)} kurulu ama hedefte yok); "
                "önce veritabanı migration öncesi kopyadan geri yüklenmeli (K-55, veritabanının "
                "yanındaki migration-backups/)"
            )
    return reasons


def manual_message(reasons: Sequence[str]) -> str:
    return (
        f"⚠ Elle kurulum gerekiyor: {'; '.join(reasons)}. Hiçbir şey değişmedi; kopyalar "
        f"yenilenince yeniden çalıştır ({MANUAL_STEPS})."
    )


@dataclass(frozen=True)
class Ortam:
    runner: Calistirici = run
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time


def say(message: str) -> None:
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, equals, value = line.partition("=")
        if equals:
            values[key.strip()] = value.strip().strip("\"'")
    return values


def systemctl(paths: Yollar, runner: Calistirici, *args: str) -> subprocess.CompletedProcess[bytes]:
    return runner(["systemctl", *args], env=paths.ortam)


def ft_command(
    paths: Yollar, profile: str, *args: str, credentials: Sequence[str] = ()
) -> list[str]:
    """ft-finans ve ft-sanal'ın kurduğu systemd-run çağrısı: ft finans olarak çalışır,
    root çalıştırmaz."""
    command = [
        "systemd-run",
        "--quiet",
        "--pipe",
        "--wait",
        "--collect",
        f"--uid={paths.kullanici}",
        f"--gid={paths.kullanici}",
        f"--working-directory={paths.veri}",
        "-p",
        f"EnvironmentFile={paths.finans_env}",
    ]
    if profile == "sanal":
        command += ["-p", "Environment=FT_PROFILE=sanal"]
    for name in credentials:
        command += ["-p", f"LoadCredential={name}:{paths.credstore / name}"]
    command += [
        "-p",
        "NoNewPrivileges=yes",
        "-p",
        "PrivateTmp=yes",
        "-p",
        "ProtectSystem=strict",
        "-p",
        f"ReadWritePaths={paths.veri}",
        "-p",
        "ProtectHome=yes",
        str(paths.repo / ".venv" / "bin" / "ft"),
        *args,
    ]
    return command


def doctor_credentials(paths: Yollar, profile: str) -> tuple[str, ...]:
    """Elle doctor gibi: web şifresi yalnız dosyası varsa yüklenir (K-126)."""
    extra = (WEB_PASSWORD,) if (paths.credstore / WEB_PASSWORD).exists() else ()
    return (*CREDENTIALS[profile], *extra)


def running_jobs(paths: Yollar, runner: Calistirici) -> list[str]:
    listed = systemctl(
        paths,
        runner,
        "list-units",
        "--type=service",
        "--state=activating,active,deactivating,reloading",
        "--no-legend",
        "--plain",
        *JOB_UNITS,
    )
    if listed.returncode:
        message = f"❌ Çalışan işler okunamadı: {last_line(listed.stderr)}. Hiçbir şey değişmedi."
        raise Durdur(Sonuc(Kod.BASARISIZ, message))
    return sorted(line.split()[0] for line in text(listed.stdout).splitlines() if line.strip())


def wait_for_jobs(paths: Yollar, env: Ortam) -> None:
    deadline = env.now() + JOB_WAIT
    while busy := running_jobs(paths, env.runner):
        if env.now() >= deadline:
            message = (
                f"⏳ Çalışan iş 10 dakikada bitmedi ({', '.join(busy)}); sonra yeniden çalıştır. "
                "Hiçbir şey değişmedi."
            )
            raise Durdur(Sonuc(Kod.MESGUL, message))
        env.sleep(POLL)


def added_migrations(paths: Yollar, current: str, sha: str, runner: Calistirici = run) -> list[str]:
    return sorted(_tree(paths, runner, sha, MIGRATIONS) - _tree(paths, runner, current, MIGRATIONS))


def check_backups(paths: Yollar, env: Ortam) -> None:
    """Yedek işi deploy'da yeniden çalıştırılmaz: aynı gün başarılı kaydı varsa atlanır (K-12).
    Bunun yerine son gece yedeğinin tazeliği ve bütünlüğü denetlenir."""
    directory = Path(read_env(paths.finans_env).get("FT_BACKUP_DIR") or paths.veri / "backups")
    problems: list[str] = []
    for profile, prefix in BACKUP_PREFIX.items():
        try:
            stamps = [path.stat().st_mtime for path in directory.glob(f"{prefix}*{BACKUP_SUFFIX}")]
        except OSError:
            stamps = []
        if not stamps:
            problems.append(f"{profile}: yedek yok")
        elif env.now() - max(stamps) > BACKUP_AGE:
            hours = int((env.now() - max(stamps)) // 3600)
            problems.append(f"{profile}: son yedek {hours} saat önce")
    for profile in PROFILES:
        verified = env.runner(ft_command(paths, profile, "backup", "verify"), env=paths.ortam)
        if verified.returncode:
            problems.append(f"{profile}: backup verify başarısız")
    if problems:
        message = (
            f"❌ Migration bekliyor ama gece yedeği güncel değil ({'; '.join(problems)}). "
            "Hiçbir şey değişmedi; yedek alınınca yeniden çalıştır."
        )
        raise Durdur(Sonuc(Kod.BASARISIZ, message))


def _checkout(paths: Yollar, runner: Calistirici, sha: str) -> subprocess.CompletedProcess[bytes]:
    return git(paths, runner, "checkout", "--quiet", "-B", "main", sha)


def _sync(paths: Yollar, runner: Calistirici) -> subprocess.CompletedProcess[bytes]:
    return runner(
        as_user(paths, "uv", "--directory", str(paths.repo), "sync", "--locked", "--no-dev"),
        env={**paths.ortam, "UV_PYTHON_INSTALL_DIR": str(paths.python)},
    )


def revert(paths: Yollar, current: str, reason: str, runner: Calistirici = run) -> Sonuc:
    """Web yeniden başlatılmadan önceki bir hatada kod önceki commit'e döner; canlı etkilenmez."""
    back = _checkout(paths, runner, current)
    done = _sync(paths, runner) if back.returncode == 0 else back
    if done.returncode:
        message = (
            f"🚨 Hazırlık başarısız ({reason}) ve önceki commit'e ({short(current)}) dönülemedi "
            f"({last_line(done.stderr)}); elle müdahale gerekiyor. Web yeniden başlatılmadı."
        )
        return Sonuc(Kod.BASARISIZ, message)
    message = (
        f"❌ Hazırlık başarısız ({reason}). Önceki commit'e ({short(current)}) dönüldü; web "
        "yeniden başlatılmadı."
    )
    return Sonuc(Kod.BASARISIZ, message)


def switch_code(paths: Yollar, sha: str, current: str, runner: Calistirici = run) -> None:
    status = git(paths, runner, "status", "--porcelain", "--untracked-files=no")
    changed = [line for line in text(status.stdout).splitlines() if line.strip()]
    if status.returncode or changed:
        message = (
            f"❌ Kurulu depoda elle yapılmış değişiklik var ({len(changed)} dosya). Hiçbir şey "
            f"değişmedi; Pi'de 'git -C {paths.repo} status' ile bak."
        )
        raise Durdur(Sonuc(Kod.BASARISIZ, message))
    checked = _checkout(paths, runner, sha)
    if checked.returncode:
        message = f"❌ {short(sha)} alınamadı: {last_line(checked.stderr)}. Hiçbir şey değişmedi."
        raise Durdur(Sonuc(Kod.BASARISIZ, message))
    synced = _sync(paths, runner)
    if synced.returncode:
        raise Durdur(revert(paths, current, f"uv sync: {last_line(synced.stderr)}", runner))


def unpack_main() -> None:
    """Ön yüz paketini finans olarak açar ve dist ile değiştirir. Kaynağı python3 -c'ye
    olduğu gibi verilir; bu yüzden kendi içinde bağımsızdır."""
    import io
    import os
    import shutil
    import sys
    import tarfile
    import tempfile

    destination, total_limit, member_limit = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".dist-yeni-", dir=parent)
    try:
        members = []
        total = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()), mode="r:gz") as archive:
                for member in archive:
                    if member.name.startswith("/") or ".." in member.name.split("/"):
                        sys.exit(f"paket reddedildi: dizin dışına yol ({member.name})")
                    if not (member.isfile() or member.isdir()):
                        sys.exit(f"paket reddedildi: yalnız dosya ve dizin ({member.name})")
                    total += member.size
                    members.append(member)
                    if len(members) > member_limit or total > total_limit:
                        sys.exit("paket reddedildi: boyut ya da dosya sayısı sınırı aşıldı")
                archive.extractall(staging, members=members, filter="data")
        except (tarfile.TarError, OSError, EOFError) as error:
            sys.exit(f"paket açılamadı: {error}")
        if not os.path.isfile(os.path.join(staging, "index.html")):
            sys.exit("paket reddedildi: index.html yok")
        old = f"{staging}-eski"
        if os.path.exists(destination):
            os.rename(destination, old)
        os.rename(staging, destination)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def unpack(paths: Yollar, package: bytes, runner: Calistirici = run) -> str | None:
    """Paketi root değil finans açar: root'un açtığı bir arşiv sisteme yazabilirdi."""
    code = f"{textwrap.dedent(inspect.getsource(unpack_main))}\nunpack_main()\n"
    done = runner(
        as_user(
            paths,
            paths.sistem_python,
            "-I",
            "-c",
            code,
            str(paths.on_yuz),
            str(UNPACKED_LIMIT),
            str(MEMBER_LIMIT),
        ),
        env=paths.ortam,
        input=package,
    )
    return None if done.returncode == 0 else last_line(done.stderr)


def migrate(paths: Yollar, runner: Calistirici = run) -> str | None:
    """Çıktı yazılmaz: CI günlüğü herkese açık, ayrıntı Pi'de."""
    for profile in PROFILES:
        done = runner(ft_command(paths, profile, "db", "migrate"), env=paths.ortam)
        if done.returncode:
            return f"{profile} profilinde migration başarısız (çıkış {done.returncode})"
    return None


def _web_state(paths: Yollar, runner: Calistirici) -> dict[str, str]:
    shown = systemctl(
        paths, runner, "show", WEB_UNIT, "--property=MainPID", "--property=ActiveState"
    )
    if shown.returncode:
        return {}
    pairs = (line.split("=", 1) for line in text(shown.stdout).splitlines() if "=" in line)
    return dict(pairs)


def restart_web(paths: Yollar, env: Ortam) -> str | None:
    """FT_WEB_PORT varsa (G4'ten sonra) sağlık ucu, yoksa yeni bir ana süreç beklenir."""
    before = _web_state(paths, env.runner).get("MainPID", "")
    restarted = systemctl(paths, env.runner, "restart", WEB_UNIT)
    if restarted.returncode:
        return f"web yeniden başlatılamadı ({last_line(restarted.stderr)})"
    port = read_env(paths.finans_env).get("FT_WEB_PORT", "")
    if port and not port.isdigit():
        return "FT_WEB_PORT sayı değil"
    deadline = env.now() + WEB_WAIT
    while True:
        if port:
            url = f"http://127.0.0.1:{port}/api/saglik"
            probe = env.runner(
                ["curl", "-fsS", "-o", "/dev/null", "--max-time", "5", url], env=paths.ortam
            )
            ready = probe.returncode == 0
        else:
            state = _web_state(paths, env.runner)
            pid = state.get("MainPID", "0")
            ready = state.get("ActiveState") == "active" and pid not in ("", "0", before)
        if ready:
            return None
        if env.now() >= deadline:
            return f"web {WEB_WAIT} saniyede hazır olmadı"
        env.sleep(POLL)


def doctor_problems(paths: Yollar, runner: Calistirici = run) -> list[str]:
    """Yalnız sorun sayısı: doctor çıktısı fon kodu ya da yol içerebilir ve CI günlüğü herkese
    açıktır."""
    problems: list[str] = []
    for profile in PROFILES:
        credentials = doctor_credentials(paths, profile)
        done = runner(
            ft_command(paths, profile, "doctor", credentials=credentials), env=paths.ortam
        )
        failed = sum(1 for line in text(done.stdout).splitlines() if line.lstrip().startswith("✗"))
        if failed:
            problems.append(f"{profile}: doctor'da {failed} sorun")
        elif done.returncode:
            problems.append(f"{profile}: doctor çalışmadı (çıkış {done.returncode})")
    return problems


def deploy(paths: Yollar, istek: Istek, package: bytes | None, env: Ortam) -> Sonuc:
    sha = istek.sha
    current = verify(paths, istek, env.runner)
    reasons = manual_reasons(paths, sha, current, istek.geri, env.runner)
    if reasons:
        return Sonuc(Kod.ELLE_KURULUM, manual_message(reasons))
    wait_for_jobs(paths, env)
    pending = added_migrations(paths, current, sha, env.runner)
    if pending:
        check_backups(paths, env)
    switch_code(paths, sha, current, env.runner)
    if package is not None:
        problem = unpack(paths, package, env.runner)
        if problem:
            return revert(paths, current, f"ön yüz paketi: {problem}", env.runner)
    back = f"Geri dönüş: workflow_dispatch, sha {current}, geri seçili."
    if pending:
        problem = migrate(paths, env.runner)
        if problem:
            message = (
                f"❌ {problem}. Kod {short(sha)}'da, web yeniden başlatılmadı. Şema geri dönmez: "
                "önce veritabanı migration öncesi kopyadan (K-55) geri yüklenmeli. Ayrıntı Pi'de: "
                f"sudo ft-finans db migrate. {back}"
            )
            return Sonuc(Kod.BASARISIZ, message)
    problems = [problem] if (problem := restart_web(paths, env)) else []
    problems += doctor_problems(paths, env.runner)
    if problems:
        restore = (
            " Migration uygulandı; geri dönmeden önce veritabanı K-55 kopyasından geri yüklenmeli."
            if pending
            else ""
        )
        message = (
            f"❌ {short(sha)} kuruldu ama sağlık denetimi başarısız: {'; '.join(problems)}. "
            f"Ayrıntı Pi'de: sudo ft-finans doctor. {back}{restore}"
        )
        return Sonuc(Kod.BASARISIZ, message)
    extras = "".join(
        [
            f"; migration: {', '.join(pending)}" if pending else "",
            "; ön yüz yenilendi" if package is not None else "",
        ]
    )
    return Sonuc(
        Kod.TAMAM, f"✅ finans güncellendi: {short(sha)} (önceki {short(current)}){extras}."
    )


def main(
    argv: Sequence[str] | None = None,
    paths: Yollar = URETIM,
    env: Ortam | None = None,
    stdin: BinaryIO | None = None,
) -> int:
    istek = parse_args(sys.argv[1:] if argv is None else argv)
    if istek is None:
        say(REFUSED)
        return Kod.RET
    package = None
    if istek.paket:
        package = (stdin or sys.stdin.buffer).read(PACKAGE_LIMIT + 1)
        if len(package) > PACKAGE_LIMIT:
            say(
                f"❌ Ön yüz paketi {PACKAGE_LIMIT // 2**20} MiB sınırını aşıyor. "
                "Hiçbir şey değişmedi."
            )
            return Kod.BASARISIZ
    try:
        with held(paths):
            result = deploy(paths, istek, package, env or Ortam())
    except Durdur as stop:
        result = stop.sonuc
    say(result.mesaj)
    return result.kod


if __name__ == "__main__":
    sys.exit(main())
