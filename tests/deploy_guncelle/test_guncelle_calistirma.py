"""finans-guncelle'nin Pi'de çağrıldığı biçim (K-140): sudo dosyayı doğrudan çalıştırır. Shebang
yoksa sudo onu /bin/sh ile çalıştırır ve kabuk Python kodunu komut sanar; 2026-11-25'te Pi'de böyle
olmuş, açıklama metnindeki ters tırnaklı yol betiği kendini sonsuza kadar çağırmıştı."""

import stat
import subprocess
import sys
from pathlib import Path

import guncelle

SCRIPT = Path(guncelle.__file__)
SHEBANG = "#!/usr/bin/python3 -I"


def test_the_script_starts_with_the_system_python_shebang() -> None:
    assert SCRIPT.read_text(encoding="utf-8").splitlines()[0] == SHEBANG


def test_the_script_is_executable_in_the_repository() -> None:
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_no_word_could_run_as_a_command_if_a_shell_read_the_file() -> None:
    assert "`" not in SCRIPT.read_text(encoding="utf-8")


def test_run_directly_without_arguments_it_refuses_and_runs_nothing(tmp_path: Path) -> None:
    """Testte /usr/bin/python3 başka bir sürüm olabilir; kopya testin Python'unu gösterir."""
    copy = tmp_path / "finans-guncelle"
    text = SCRIPT.read_text(encoding="utf-8")
    copy.write_text(text.replace(SHEBANG, f"#!{sys.executable} -I", 1), encoding="utf-8")
    copy.chmod(0o755)

    done = subprocess.run(  # noqa: S603 - testin kendi kopyası
        [str(copy)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert (done.returncode, done.stdout, done.stderr) == (3, f"{guncelle.REFUSED}\n", "")
