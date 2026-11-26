"""Mac'te yedek çekme (K-143): betik doğrudan, sahte rsync, osascript, scutil ve curl ile
çalıştırılır; launchd de onu doğrudan çalıştırır."""

import hashlib
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pull_backups.sh"
URL = "https://hc-ping.example/deneme-kontrol"
HOST = "finans-yedek"
# Sahte rsync'in hata metni gerçek ssh'inki gibi adres içerir; bildirime ve ping'e gitmemeli.
LEAK = "100.64.0.9"
FAKES = {
    "rsync": f"""#!/bin/bash
printf '%s\\n' "$*" >> "$SAHTE_GUNLUK/rsync"
kalan=$(cat "$SAHTE_GUNLUK/kalan-hata")
if [ "$kalan" -gt 0 ]; then
  echo $((kalan - 1)) > "$SAHTE_GUNLUK/kalan-hata"
  echo "ssh: connect to host {LEAK} port 22: Operation timed out" >&2
  exit 255
fi
for f in "$SAHTE_KAYNAK"/*; do [ -e "$f" ] && cp -p "$f" "${{@: -1}}"; done
exit 0
""",
    "scutil": """#!/bin/bash
echo "* (${SAHTE_TAILSCALE})  0000 VPN (io.tailscale.ipn.macsys) \\"Tailscale\\"  [VPN]"
""",
    "osascript": """#!/bin/bash
cat > /dev/null
printf '%s\\n' "$2" >> "$SAHTE_GUNLUK/osascript"
""",
    "curl": """#!/bin/bash
url=$(sed -n 's/^url = "\\(.*\\)"$/\\1/p')
printf '%s | %s\\n' "$url" "$*" >> "$SAHTE_GUNLUK/curl"
""",
}
FINANS = "finans-20261126T001500Z.db.age"
SANAL = "sanal-20261126T001502Z.db.age"


class Mac:
    def __init__(self, root: Path) -> None:
        self.bin = root / "bin"
        self.source = root / "sunucu"
        self.target = root / "Yedekler" / "finans"
        self.logs = root / "gunluk"
        self.home = root / "ev"
        for directory in (self.bin, self.source, self.logs, self.home):
            directory.mkdir(parents=True)
        for name, body in FAKES.items():
            (self.bin / name).write_text(body, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.ping = self.home / ".config" / "finans" / "yedek-cek.ping"
        self.ping.parent.mkdir(parents=True)
        self.ping.write_text(f"{URL}\n", encoding="utf-8")
        self.ping.chmod(0o600)

    def backup(
        self, name: str, *, hours: float = 6, sidecar: str | None = None, content: bytes = b"age"
    ) -> None:
        path = self.source / name
        path.write_bytes(content)
        digest = sidecar if sidecar is not None else hashlib.sha256(content).hexdigest()
        if digest:
            path.with_name(f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
        stamp = time.time() - hours * 3600
        for item in (path, path.with_name(f"{name}.sha256")):
            if item.exists():
                os.utime(item, (stamp, stamp))

    def run(
        self, *, failures: int = 0, tailscale: str = "Connected", rsync: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        (self.logs / "kalan-hata").write_text(str(failures), encoding="utf-8")
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "FINANS_YEDEK_RSYNC": str(rsync or self.bin / "rsync"),
            "FINANS_YEDEK_BEKLEME": "0",
            "SAHTE_KAYNAK": str(self.source),
            "SAHTE_GUNLUK": str(self.logs),
            "SAHTE_TAILSCALE": tailscale,
        }
        return subprocess.run(
            [str(SCRIPT), HOST, str(self.target)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self, tool: str) -> list[str]:
        path = self.logs / tool
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.fixture
def mac(tmp_path: Path) -> Mac:
    return Mac(tmp_path)


def test_the_script_runs_directly_and_explains_its_usage() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/bin/bash\n")
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "Kullanım:" in result.stderr


def test_a_good_pull_pings_healthchecks_and_stays_quiet(mac: Mac) -> None:
    mac.backup(FINANS)
    mac.backup(SANAL)

    result = mac.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in mac.target.iterdir()) == sorted(
        [FINANS, f"{FINANS}.sha256", SANAL, f"{SANAL}.sha256"]
    )
    assert stat.S_IMODE(mac.target.stat().st_mode) == 0o700
    assert mac.calls("rsync") == [
        "-a --ignore-existing --exclude .* --include *.db.age --include *.db.age.sha256 "
        f"--exclude * -e ssh -o BatchMode=yes -o ConnectTimeout=30 {HOST}:/ {mac.target}/"
    ]
    [ping] = mac.calls("curl")
    assert ping.startswith(f"{URL} | ")
    assert "--data-raw tamam: 2 yedek" in ping
    assert URL not in ping.split(" | ", 1)[1]
    assert mac.calls("osascript") == []
    assert "tamam: 2 yedek, özetler tutuyor" in result.stdout


def test_short_outages_are_retried(mac: Mac) -> None:
    mac.backup(FINANS)

    result = mac.run(failures=2, tailscale="Disconnected")

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(mac.calls("rsync")) == 3
    assert "çekme başarısız (deneme 1/3, Tailscale: kapalı)" in result.stdout
    assert "çekme başarısız (deneme 2/3, Tailscale: kapalı)" in result.stdout
    assert [call.split(" | ")[0] for call in mac.calls("curl")] == [URL]


def test_an_unreachable_server_notifies_without_leaking_details(mac: Mac) -> None:
    mac.backup(FINANS)

    result = mac.run(failures=5, tailscale="Disconnected")

    assert result.returncode == 1
    assert len(mac.calls("rsync")) == 3
    reason = "sunucudan çekilemedi: 3 deneme (Tailscale: kapalı)"
    assert mac.calls("osascript") == [reason]
    [ping] = mac.calls("curl")
    assert ping.startswith(f"{URL}/fail | ")
    assert f"--data-raw {reason}" in ping
    assert LEAK not in "".join(mac.calls("osascript") + mac.calls("curl"))


def test_damaged_or_unverifiable_backups_fail(mac: Mac) -> None:
    mac.backup(FINANS)
    mac.backup(SANAL, sidecar="0" * 64)
    mac.backup("sanal-20261125T001502Z.db.age", sidecar="")

    result = mac.run()

    assert result.returncode == 1
    [message] = mac.calls("osascript")
    assert f"{SANAL}: özet tutmuyor" in message
    assert "sanal-20261125T001502Z.db.age: özet dosyası yok" in message
    assert FINANS not in message


def test_stale_or_missing_backups_fail(mac: Mac) -> None:
    mac.backup(SANAL, hours=30)

    result = mac.run()

    assert result.returncode == 1
    [message] = mac.calls("osascript")
    assert "finans yedeği yok" in message
    assert "en yeni sanal yedeği 26 saatten eski" in message


def test_an_old_backup_is_fine_when_a_fresh_one_exists(mac: Mac) -> None:
    mac.backup("finans-20261101T001500Z.db.age", hours=600)
    mac.backup(FINANS, hours=25)

    assert mac.run().returncode == 0


def test_unexpected_files_in_the_mac_folder_fail(mac: Mac) -> None:
    mac.backup(FINANS)
    mac.target.mkdir(parents=True)
    (mac.target / "finans-20261125T134401Z-v4.db").write_bytes(b"SQLite format 3")
    (mac.target / ".DS_Store").write_bytes(b"")

    result = mac.run()

    assert result.returncode == 1
    [message] = mac.calls("osascript")
    assert message == "beklenmeyen dosya: finans-20261125T134401Z-v4.db"


def test_a_loose_ping_file_is_not_used(mac: Mac) -> None:
    mac.backup(FINANS)
    mac.ping.chmod(0o644)

    result = mac.run()

    assert result.returncode == 1
    assert mac.calls("curl") == []
    [message] = mac.calls("osascript")
    assert message.startswith("ping dosyasının izni 600 değil, adres kullanılmadı")
    assert (mac.target / FINANS).exists()


def test_without_a_ping_file_the_pull_still_works(mac: Mac) -> None:
    mac.backup(FINANS)
    mac.ping.unlink()

    result = mac.run()

    assert result.returncode == 0
    assert mac.calls("curl") == []
    assert "ping dosyası yok" in result.stdout


def test_a_missing_rsync_fails_at_once(mac: Mac, tmp_path: Path) -> None:
    result = mac.run(rsync=tmp_path / "yok" / "rsync")

    assert result.returncode == 1
    assert mac.calls("rsync") == []
    [message] = mac.calls("osascript")
    assert message.startswith("rsync yok: ")
