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

# Detach and reload the gate before deleting gate.php. Reversing this order
# can make PHP fail on a missing auto_prepend_file during uninstall.
backup_dir="$(mktemp -d /tmp/immution-uninstall.XXXXXXXX)"
restore_ini() {
    status=$?
    trap - ERR
    for ini in "${ini_files[@]}"; do
        if [[ -f "$backup_dir$ini" ]]; then
            cp -a -- "$backup_dir$ini" "$ini"
        fi
    done
    printf 'Apache detach failed; installation retained. Snapshot: %s\n' "$backup_dir" >&2
    exit "$status"
}
shopt -s nullglob
ini_files=(/etc/php/*/apache2/conf.d/99-immution.ini)
shopt -u nullglob
trap restore_ini ERR
for ini in "${ini_files[@]}"; do
    if grep -q '^auto_prepend_file = /opt/immution/gate.php$' "$ini"; then
        cp -a --parents -- "$ini" "$backup_dir"
        rm -f -- "$ini"
    fi
done

apache2ctl configtest
systemctl reload apache2
trap - ERR
rm -rf -- "$backup_dir"

systemctl disable --now immution
rm -f /etc/systemd/system/immution.service /etc/logrotate.d/immution
rm -rf /opt/immution
systemctl daemon-reload

if $PURGE; then
    rm -rf /etc/immution /var/log/immution /run/immution
    userdel immution >/dev/null 2>&1 || true
    printf 'Immution and its configuration/logs were removed.\n'
else
    printf 'Immution removed. Configuration and logs were preserved.\n'
    printf 'Use --purge to remove /etc/immution and /var/log/immution too.\n'
fi
