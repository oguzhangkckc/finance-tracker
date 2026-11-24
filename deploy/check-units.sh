#!/usr/bin/env bash
# CI: systemd birimlerini systemd-analyze ile doğrular (K-80); yalnızca Linux'ta çalışır.
set -euo pipefail

units="$(cd "$(dirname "$0")/systemd" && pwd)"

for timer in "$units"/*.timer; do
  expression="$(sed -n 's/^OnCalendar=//p' "$timer")"
  echo "$(basename "$timer"): $expression"
  systemd-analyze calendar "$expression" > /dev/null
done

# Şablon doğrudan doğrulanamaz; her iş için bir örnek kopyası kurulur. ExecStart ve
# EnvironmentFile sunucudaki yollara işaret ettiği için CI'da zararsız değerlerle değişir.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp "$units"/*.timer "$work"/
for timer in "$units"/*.timer; do
  instance="$(sed -n 's/^Unit=//p' "$timer")"
  sed -e 's#^ExecStart=.*#ExecStart=/bin/true#' -e '/^EnvironmentFile=/d' \
    "$units/finans-job@.service" > "$work/$instance"
done
systemd-analyze verify --man=no "$work"/*.timer "$work"/finans-job@?*.service
echo "systemd birimleri geçerli."
