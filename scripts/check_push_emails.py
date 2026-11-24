"""pre-push: push edilecek her commit'in yazar ve committer e-postası GitHub noreply olmalı.

pre-commit, push edilen ucu PRE_COMMIT_TO_REF ile verir; elle çalıştırmada ilk argüman ya da HEAD.
"""

import os
import re
import subprocess
import sys

NOREPLY = re.compile(
    r"^(?:\d+\+)?[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?@users\.noreply\.github\.com$"
)
AMEND = (
    "git rebase --exec 'git commit --amend --no-edit "
    '--author="$(git config user.name) <$(git config user.email)>"\' {base}'
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _outgoing(tip: str) -> list[str]:
    # Uzak izleme dallarındaki commit'ler zaten yayımlanmış; yalnızca yeni olanlar denetlenir.
    return _git("rev-list", tip, "--not", "--remotes").split()


def _violations(commits: list[str]) -> list[tuple[str, str, str]]:
    found = []
    for sha in commits:
        short, author, committer, subject = (
            _git("show", "-s", "--format=%h%x00%ae%x00%ce%x00%s", sha).rstrip("\n").split("\0")
        )
        roles = [
            role
            for role, email in (("yazar", author), ("committer", committer))
            if not NOREPLY.match(email)
        ]
        if roles:
            found.append((short, " ve ".join(roles), subject))
    return found


def _configured_email() -> str:
    result = subprocess.run(
        ["git", "config", "--get", "user.email"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def main() -> int:
    tip = os.environ.get("PRE_COMMIT_TO_REF") or (sys.argv[1] if len(sys.argv) > 1 else "HEAD")
    if set(tip) == {"0"}:
        return 0
    violations = _violations(_outgoing(tip))
    if not violations:
        return 0
    print("Push durduruldu: bu commit'lerde e-posta GitHub noreply adresi değil:")
    for short, roles, subject in violations:
        print(f"  {short} ({roles}): {subject}")
    oldest = violations[-1][0]
    has_parent = len(_git("rev-list", "--parents", "-n", "1", oldest).split()) > 1
    print("Düzeltme:")
    if NOREPLY.match(_configured_email()):
        print("  1) Bu repodaki user.email zaten noreply; bu adımı atla.")
    else:
        print('  1) git config --local user.email "<id>+<kullanıcı>@users.noreply.github.com"')
    print(f"  2) {AMEND.format(base=f'{oldest}^' if has_parent else '--root')}")
    print("  3) Push'u tekrarla.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
