#!/usr/bin/env bash
# Mac'te gece yedeğinin tam geri yükleme testi (K-82): özet, çözme ve bütünlük denetimi.
# Sunucu yedeği çözemez; age gizli anahtarı yalnızca burada durur.
# Kullanım: scripts/verify_backup.sh <finans-…db.age> <age-anahtar-dosyası>
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Kullanım: $0 <finans-…db.age> <age-anahtar-dosyası>" >&2
  exit 2
fi
backup="$1"
identity="$2"
sidecar="$backup.sha256"
[ -f "$sidecar" ] || { echo "Özet dosyası yok: $sidecar" >&2; exit 1; }

(cd "$(dirname "$backup")" && shasum -a 256 -c "$(basename "$sidecar")")

work="$(mktemp -d)"
chmod 700 "$work"
trap 'rm -rf "$work"' EXIT
age -d -i "$identity" -o "$work/finans.db" "$backup"
chmod 600 "$work/finans.db"

result="$(sqlite3 "$work/finans.db" 'PRAGMA integrity_check')"
if [ "$result" != "ok" ]; then
  echo "Bütünlük denetimi başarısız: $result" >&2
  exit 1
fi
echo "Bütünlük: ok"
sqlite3 "$work/finans.db" \
  "SELECT 'şema sürümü ' || user_version FROM pragma_user_version;
   SELECT 'işlem ' || count(*) FROM txn;
   SELECT 'fiyat ' || count(*) FROM price;
   SELECT 'TÜFE ' || count(*) FROM cpi;"
