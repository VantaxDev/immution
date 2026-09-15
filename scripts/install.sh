#!/usr/bin/env bash
set -Eeuo pipefail

MODE="monitor"
INSTALL_DIR="/opt/immution"
CONFIG_DIR="/etc/immution"
SERVICE_FILE="/etc/systemd/system/immution.service"
LOGROTATE_FILE="/etc/logrotate.d/immution"

usage() {
    printf '%s\n' \
        "Usage: sudo ./scripts/install.sh [--mode monitor|block]" \
        "" \
        "The default is monitor mode. Use block mode only after reviewing" \
        "would_block events on the target server."
}

while (($#)); do
    case "$1" in
        --mode)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            MODE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$MODE" != "monitor" && "$MODE" != "block" ]]; then
    printf 'Invalid mode: %s\n' "$MODE" >&2
    exit 2
fi

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    printf 'Run this installer as root: sudo ./scripts/install.sh\n' >&2
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

required_files=(
    "$ROOT_DIR/src/immution.py"
    "$ROOT_DIR/src/gate.php"
    "$ROOT_DIR/tools/immutionctl.py"
    "$ROOT_DIR/config/daemon.json"
    "$ROOT_DIR/config/gate-config.php.example"
    "$ROOT_DIR/packaging/immution.service"
    "$ROOT_DIR/packaging/immution.logrotate"
)
for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        printf 'Missing release file: %s\n' "$file" >&2
        exit 1
    fi
done

for command in apache2ctl getent install php python3 systemctl useradd usermod mktemp cp; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command" >&2
        exit 1
    fi
done

python_version="$(python3 -c 'import sys; print(".".join(str(part) for part in sys.version_info[:3]))')"
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 6) else 1)'; then
    printf 'Immution requires Python 3.6 or newer; python3 reported: %s\n' \
        "${python_version:-unknown}" >&2
    exit 1
fi
python3 -m py_compile "$ROOT_DIR/src/immution.py" "$ROOT_DIR/tools/immutionctl.py"

php_version_id="$(php -r 'echo PHP_VERSION_ID;')"
if [[ ! "$php_version_id" =~ ^[0-9]+$ ]] || ((php_version_id < 70000)); then
    printf 'Immution requires PHP 7.0 or newer; PHP CLI reported version id: %s\n' \
        "${php_version_id:-unknown}" >&2
    exit 1
fi
php -l "$ROOT_DIR/src/gate.php" >/dev/null
php -l "$ROOT_DIR/config/gate-config.php.example" >/dev/null

if ! getent group www-data >/dev/null; then
    printf 'Required group not found: www-data\n' >&2
    exit 1
fi
if ! getent group adm >/dev/null; then
    printf 'Required group not found: adm\n' >&2
    exit 1
fi

# Stale config directories are not proof that Apache actually loads mod_php.
apache2ctl -M 2>/dev/null | grep -Eq 'php[0-9]*_module' || {
    printf 'Apache must have mod_php loaded; PHP-FPM requires manual setup.\n' >&2
    exit 1
}

shopt -s nullglob
php_conf_dirs=(/etc/php/*/apache2/conf.d)
php_roots=(/etc/php/*/apache2)
shopt -u nullglob
if ((${#php_conf_dirs[@]} == 0)); then
    printf 'No Apache PHP configuration directory found under /etc/php/*/apache2/conf.d\n' >&2
    printf 'Immution v0.1 supports Apache with mod_php. PHP-FPM requires manual setup.\n' >&2
    exit 1
fi

# auto_prepend_file can contain only one file. Refuse to silently override an
# existing application/security bootstrap.
conflicts=""
for root in "${php_roots[@]}"; do
    while IFS= read -r line; do
        [[ "$line" == *"/opt/immution/gate.php"* ]] && continue
        conflicts+="$line"$'\n'
    done < <(grep -RInE '^[[:space:]]*auto_prepend_file[[:space:]]*=[[:space:]]*[^;[:space:]]+' "$root" 2>/dev/null || true)
done
if [[ -n "$conflicts" ]]; then
    printf 'Existing auto_prepend_file configuration detected; installation stopped:\n%s' "$conflicts" >&2
    printf 'Chain the existing bootstrap manually before installing Immution.\n' >&2
    exit 1
fi

if ! id immution >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin immution
fi
usermod -a -G adm immution

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir=""
service_backup=""
created_ini=()
# Snapshot overwritten configuration too. Rollback must restore the previous
# prepend file before reloading Apache; otherwise every PHP request can fail.
transaction_dir="$(mktemp -d /tmp/immution-install.XXXXXXXX)"
restore_targets=("$CONFIG_DIR" "$SERVICE_FILE" "$LOGROTATE_FILE")
for conf_dir in "${php_conf_dirs[@]}"; do
    restore_targets+=("$conf_dir/99-immution.ini")
done
for target in "${restore_targets[@]}"; do
    if [[ -e "$target" || -L "$target" ]]; then
        cp -a --parents -- "$target" "$transaction_dir"
    fi
done
was_active=false
was_enabled=false
systemctl is-active --quiet immution && was_active=true
systemctl is-enabled --quiet immution && was_enabled=true

rollback() {
    status=$?
    trap - ERR
    printf 'Installation failed; rolling back.\n' >&2
    systemctl stop immution >/dev/null 2>&1 || true
    for target in "${restore_targets[@]}"; do
        rm -rf -- "$target"
        if [[ -e "$transaction_dir$target" || -L "$transaction_dir$target" ]]; then
            cp -a -- "$transaction_dir$target" "$target"
        fi
    done
    if [[ -n "$backup_dir" && -d "$backup_dir" ]]; then
        rm -rf -- "$INSTALL_DIR"
        mv -- "$backup_dir" "$INSTALL_DIR"
    elif [[ -z "$backup_dir" ]]; then
        rm -rf -- "$INSTALL_DIR"
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
    if $was_enabled; then
        systemctl enable immution >/dev/null 2>&1 || true
    else
        systemctl disable immution >/dev/null 2>&1 || true
    fi
    if $was_active; then
        systemctl start immution >/dev/null 2>&1 || true
    fi
    apache2ctl configtest && systemctl reload apache2 || true
    printf 'Rollback snapshot retained at %s for inspection.\n' "$transaction_dir" >&2
    exit "$status"
}
trap rollback ERR

if [[ -d "$INSTALL_DIR" ]]; then
    backup_dir="${INSTALL_DIR}.backup-${timestamp}"
    mv -- "$INSTALL_DIR" "$backup_dir"
fi
if [[ -f "$SERVICE_FILE" ]]; then
    service_backup="${SERVICE_FILE}.backup-${timestamp}"
    cp -a -- "$SERVICE_FILE" "$service_backup"
fi

install -d -o root -g root -m 0755 "$INSTALL_DIR"
install -o root -g root -m 0755 "$ROOT_DIR/src/immution.py" "$INSTALL_DIR/immution.py"
install -o root -g root -m 0644 "$ROOT_DIR/src/gate.php" "$INSTALL_DIR/gate.php"
install -o root -g root -m 0755 "$ROOT_DIR/tools/immutionctl.py" "$INSTALL_DIR/immutionctl.py"

install -d -o root -g www-data -m 0750 "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/daemon.json" ]]; then
    install -o root -g root -m 0644 "$ROOT_DIR/config/daemon.json" "$CONFIG_DIR/daemon.json"
fi
if [[ ! -f "$CONFIG_DIR/gate-config.php" ]]; then
    install -o root -g www-data -m 0640 "$ROOT_DIR/config/gate-config.php.example" "$CONFIG_DIR/gate-config.php"
    if [[ "$MODE" == "block" ]]; then
        sed -i "s/'mode' => 'monitor'/'mode' => 'block'/" "$CONFIG_DIR/gate-config.php"
    fi
else
    printf 'Keeping existing %s/gate-config.php (requested --mode is not applied).\n' "$CONFIG_DIR"
fi

install -o root -g root -m 0644 "$ROOT_DIR/packaging/immution.service" "$SERVICE_FILE"
install -o root -g root -m 0644 "$ROOT_DIR/packaging/immution.logrotate" "$LOGROTATE_FILE"
install -d -o immution -g www-data -m 0770 /var/log/immution

for conf_dir in "${php_conf_dirs[@]}"; do
    ini="$conf_dir/99-immution.ini"
    if [[ ! -e "$ini" ]]; then
        created_ini+=("$ini")
    fi
    printf '; Managed by Immution\nauto_prepend_file = /opt/immution/gate.php\n' > "$ini"
    chmod 0644 "$ini"
done

apache2ctl configtest
systemctl daemon-reload
systemctl enable immution >/dev/null
systemctl restart immution
systemctl reload apache2

if ! systemctl is-active --quiet immution; then
    journalctl -u immution -n 30 --no-pager >&2 || true
    false
fi

# Existing configuration wins on upgrades; never claim monitor solely from
# the command-line default when the preserved gate is actually blocking.
MODE="$(php -r '$c = require "/etc/immution/gate-config.php"; echo isset($c["mode"]) && $c["mode"] === "block" ? "block" : "monitor";')"

trap - ERR
rm -rf -- "$transaction_dir"
if [[ -n "$service_backup" ]]; then
    rm -f -- "$service_backup"
fi

printf '\nImmution installed successfully.\n'
printf 'Configured mode: %s\n' "$MODE"
printf 'Events: /var/log/immution/events.csv\n'
printf 'Service: systemctl status immution\n'
printf 'Explain: sudo /opt/immution/immutionctl.py status\n'
if [[ "$MODE" == "monitor" ]]; then
    printf '\nNo requests are being blocked. Review would_block events before enabling block mode.\n'
fi
if [[ -n "$backup_dir" ]]; then
    printf 'Previous installation backup: %s\n' "$backup_dir"
fi
