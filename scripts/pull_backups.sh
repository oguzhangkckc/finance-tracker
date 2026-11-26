#!/bin/bash
# Mac'te gece yedeklerini sunucudan çeker ve denetler (K-143). launchd bu dosyanın
# ~/.local/bin/finans-yedek-cek kopyasını çalıştırır; repo takılı olmayan bir diskte olabilir.
# Kullanım: finans-yedek-cek <ssh takma adı> <hedef dizin>
set -u

DENEME=3
TAZE_DAKIKA=$((26 * 60))
AD='^(finans|sanal)-[0-9]{8}T[0-9]{6}Z\.db\.age(\.sha256)?$'

if [ "$#" -ne 2 ]; then
  echo "Kullanım: $0 <ssh takma adı> <hedef dizin>" >&2
  exit 2
fi
sunucu="$1"
hedef="${2%/}"
rsync="${FINANS_YEDEK_RSYNC:-/opt/homebrew/bin/rsync}"
bekleme="${FINANS_YEDEK_BEKLEME:-300}"
ping_dosyasi="${FINANS_YEDEK_PING:-$HOME/.config/finans/yedek-cek.ping}"
adres=""
sorun=""

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

ekle() { sorun="${sorun:+$sorun; }$1"; }

ping_gonder() {
  [ -n "$adres" ] || return 0
  # Adres sırdır: süreç listesinde görünmesin diye curl'e standart girdiden verilir.
  printf 'url = "%s%s"\n' "$adres" "$1" |
    curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "$2" -K - ||
    log "healthchecks'e ulaşılamadı"
}

basarisiz() {
  log "BAŞARISIZ: $1"
  osascript - "$1" >/dev/null 2>&1 <<'EOF' || log "bildirim gösterilemedi"
on run argv
  display notification (item 1 of argv) with title "finans: yedek çekme başarısız" sound name "Basso"
end run
EOF
  ping_gonder /fail "$1"
  exit 1
}

tailscale_durumu() {
  local satir
  satir="$(scutil --nc list 2>/dev/null | grep -i tailscale | head -n 1)"
  case "$satir" in
    "") echo "bulunamadı" ;;
    *"(Connected)"*) echo "bağlı" ;;
    *"(Disconnected)"*) echo "kapalı" ;;
    *) printf '%s\n' "$satir" | sed -E 's/^[^(]*\(([^)]*)\).*$/\1/' ;;
  esac
}

if [ -f "$ping_dosyasi" ]; then
  if [ -n "$(find "$ping_dosyasi" -prune -perm 0600)" ]; then
    adres="$(head -n 1 "$ping_dosyasi" | tr -d '[:space:]')"
    adres="${adres%/}"
    [ -n "$adres" ] || log "ping dosyası boş; healthchecks'e bildirilmiyor"
  else
    ekle "ping dosyasının izni 600 değil, adres kullanılmadı (chmod 600 $ping_dosyasi)"
  fi
else
  log "ping dosyası yok ($ping_dosyasi); healthchecks'e bildirilmiyor"
fi

[ -x "$rsync" ] || basarisiz "rsync yok: $rsync (GNU rsync gerekir: brew install rsync, K-100)"
mkdir -p -m 700 "$hedef" || basarisiz "hedef dizin oluşturulamadı: $hedef"

deneme=1
until "$rsync" -a --ignore-existing --exclude '.*' --include '*.db.age' \
  --include '*.db.age.sha256' --exclude '*' \
  -e 'ssh -o BatchMode=yes -o ConnectTimeout=30' "$sunucu:/" "$hedef/"; do
  durum="$(tailscale_durumu)"
  log "çekme başarısız (deneme $deneme/$DENEME, Tailscale: $durum)"
  if [ "$deneme" -ge "$DENEME" ]; then
    basarisiz "sunucudan çekilemedi: $DENEME deneme (Tailscale: $durum)"
  fi
  deneme=$((deneme + 1))
  sleep "$bekleme"
done

cd "$hedef" || basarisiz "hedef dizine girilemedi: $hedef"

for f in *.db.age; do
  [ -f "$f" ] || continue
  if [ ! -f "$f.sha256" ]; then
    ekle "$f: özet dosyası yok"
  elif ! shasum -a 256 -c --status "$f.sha256"; then
    ekle "$f: özet tutmuyor"
  fi
done

for onek in finans sanal; do
  if [ -z "$(find . -maxdepth 1 -type f -name "$onek-*.db.age" | head -n 1)" ]; then
    [ "$onek" = sanal ] || ekle "finans yedeği yok"
    continue
  fi
  if [ -z "$(find . -maxdepth 1 -type f -name "$onek-*.db.age" -mmin "-$TAZE_DAKIKA" | head -n 1)" ]; then
    ekle "en yeni $onek yedeği 26 saatten eski; sunucuda gece yedeği alınmamış olabilir"
  fi
done

for f in * .[!.]* ..?*; do
  [ -e "$f" ] || [ -L "$f" ] || continue
  [ "$f" = .DS_Store ] && continue
  if [ -L "$f" ] || [ ! -f "$f" ] || ! printf '%s\n' "$f" | grep -Eq "$AD"; then
    ekle "beklenmeyen dosya: $f"
  fi
done

[ -z "$sorun" ] || basarisiz "$sorun"

sayi="$(find . -maxdepth 1 -type f -name '*.db.age' | wc -l | tr -d ' ')"
log "tamam: $sayi yedek, özetler tutuyor"
ping_gonder "" "tamam: $sayi yedek"
exit 0
