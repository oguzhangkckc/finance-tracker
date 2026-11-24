import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_backup.sh"


def test_mac_script_parses_and_explains_its_usage() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "Kullanım:" in result.stderr
