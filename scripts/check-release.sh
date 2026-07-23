#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$ROOT_DIR"

for command in python3 php bash; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Required check command not found: %s\n' "$command" >&2
        exit 1
    fi
done

printf '%s\n' '[1/6] Python unit and regression tests'
python3 -m unittest discover -s tests -v

printf '%s\n' '[2/6] Python compilation'
python3 -m py_compile src/immution.py tools/*.py

printf '%s\n' '[3/6] Shell syntax'
bash -n scripts/*.sh

printf '%s\n' '[4/6] PHP syntax'
php -l src/gate.php
php -l config/gate-config.php.example
php -l experimental/gate_optimized.php
php -d display_errors=1 -d error_reporting=E_ALL tests/test_php_gate.php

printf '%s\n' '[5/6] Configuration and fixture discovery'
python3 src/immution.py \
    --config config/daemon.json \
    --check-config \
    tests/fixtures/access.log

printf '%s\n' '[6/6] systemd unit'
if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify packaging/immution.service
else
    printf '%s\n' 'SKIP: systemd-analyze is not installed'
fi

if [[ -d .git ]]; then
    git diff --check
fi

printf '%s\n' 'All source release checks passed.'
