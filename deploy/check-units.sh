#!/usr/bin/env bash
# CI: systemd birimlerini systemd-analyze ile doğrular (K-80); yalnızca Linux'ta çalışır.
set -euo pipefail

units="$(cd "$(dirname "$0")/systemd" && pwd)"

for timer in "$units"/*.timer; do
  while IFS= read -r expression; do
    echo "$(basename "$timer"): $expression"
    systemd-analyze calendar "$expression" > /dev/null
  done < <(sed -n 's/^OnCalendar=//p' "$timer")
done

# Şablon doğrudan doğrulanamaz; her iş için kendi şablonundan (gerçek ya da sanal) bir örnek kurulur. ExecStart ve
# EnvironmentFile sunucudaki yollara işaret ettiği için CI'da zararsız değerlerle değişir.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
harmless() {
  sed -e 's#^ExecStart=.*#ExecStart=/bin/true#' -e '/^EnvironmentFile=/d' "$1" > "$2"
}
cp "$units"/*.timer "$units"/*.path "$work"/
cp -R "$units/finans-web.service.d" "$work"/
for timer in "$units"/*.timer; do
  instance="$(sed -n 's/^Unit=//p' "$timer")"
  harmless "$units/${instance%%@*}@.service" "$work/$instance"
done
for service in finans-web finans-refresh finans-sanal-refresh; do
  harmless "$units/$service.service" "$work/$service.service"
done
systemd-analyze verify --man=no "$work"/*.timer "$work"/*.path "$work"/finans-*job@?*.service \
  "$work"/finans-web.service "$work"/finans-*refresh.service
echo "systemd birimleri geçerli."

# K-124, K-136: ağa açık tek servisin sertleştirmesi gevşerse CI kırılır (eşik 0-100 ölçeğinde).
# G4'te systemd 255 (ubuntu-24.04) ile ölçülen 1.5'tir; ağ erişimi PrivateNetwork'ün 0.8'ini yükseltti.
systemd-analyze security --offline=yes --threshold=15 "$work"/finans-web.service
