#!/usr/bin/env bash
set -Eeuo pipefail

PURGE=false
if [[ ${1:-} == "--purge" ]]; then
    PURGE=true
elif [[ $# -gt 0 ]]; then
    printf 'Usage: sudo ./scripts/uninstall.sh [--purge]\n' >&2
    exit 2
fi

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    printf 'Run as root.\n' >&2
    exit 1
fi

systemctl disable --now immution >/dev/null 2>&1 || true
rm -f /etc/systemd/system/immution.service /etc/logrotate.d/immution

shopt -s nullglob
ini_files=(/etc/php/*/apache2/conf.d/99-immution.ini)
shopt -u nullglob
for ini in "${ini_files[@]}"; do
    if grep -q '^auto_prepend_file = /opt/immution/gate.php$' "$ini"; then
        rm -f -- "$ini"
    fi
done

rm -rf /opt/immution
systemctl daemon-reload

if command -v apache2ctl >/dev/null 2>&1 && apache2ctl configtest; then
    systemctl reload apache2 || true
fi

if $PURGE; then
    rm -rf /etc/immution /var/log/immution /run/immution
    userdel immution >/dev/null 2>&1 || true
    printf 'Immution and its configuration/logs were removed.\n'
else
    printf 'Immution removed. Configuration and logs were preserved.\n'
    printf 'Use --purge to remove /etc/immution and /var/log/immution too.\n'
fi
