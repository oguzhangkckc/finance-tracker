"""finans-guncelle: CI'nın tek SSH çağrısıyla çalıştırdığı deploy betiği (K-140).

Pi'deki root sahipli kopyası `/usr/local/sbin/finans-guncelle`'dir; sudoers'ta yalnız o
`NOPASSWD`'dir. Sistem Python'uyla (3.12) ve yalnız standart kütüphaneyle çalışır.
`/opt/finans` `finans`'ındır; root oradaki hiçbir dosyayı çalıştırmaz, git ve uv'yi
`runuser -u finans` ile çağırır.
"""

import fcntl
import os
import re
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Final, Protocol


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
    """Yalnız `<sha> [--geri] [--paket -]`. argparse kendi kodu 2 ile çıkardı; burada 2 elle
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
    """`O_NOFOLLOW`: kilit yolundaki bir sembolik bağlantı root'a başka bir dosya açtırmasın."""
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
    """Kurulu commit'i döndürür. Hedef `main`'in atası olmalı; `--geri` yoksa kurulu commit de
    hedefin atası olmalı."""
    head = git(paths, runner, "rev-parse", "HEAD")
    if head.returncode:
        message = f"❌ Kurulu commit okunamadı: {last_line(head.stderr)}."
        raise Durdur(Sonuc(Kod.BASARISIZ, message))
    current = text(head.stdout).strip()
    if current == istek.sha:
        raise Durdur(Sonuc(Kod.TAMAM, f"{short(istek.sha)} zaten kurulu; bir şey yapılmadı."))
    # Bütün dallar çekilir: başka daldaki bir commit "bulunamadı" değil "`main`'de yok" diye
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
        raise Durdur(Sonuc(Kod.RET, f"⛔ Reddedildi: {short(istek.sha)} `main`'de yok."))
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
    """Yalnız bu projenin birimleri; `*.wants` bağları ve diğer servisler sayılmaz."""
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
    olmalı: root `finans`'ın yazabildiği dizinden kopyalamaz. Geri dönüş şemayı geri almaz."""
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
                "yanındaki backups/)"
            )
    return reasons


def manual_message(reasons: Sequence[str]) -> str:
    return (
        f"⚠ Elle kurulum gerekiyor: {'; '.join(reasons)}. Hiçbir şey değişmedi; kopyalar "
        f"yenilenince yeniden çalıştır ({MANUAL_STEPS})."
    )
