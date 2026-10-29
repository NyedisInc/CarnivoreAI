#!/usr/bin/env bash
set -uo pipefail

DEFAULT_SCAN_DIRS=("client" "macOS")

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

targets=()
if [ "$#" -gt 0 ]; then
    targets+=("$1")
else
    for d in "${DEFAULT_SCAN_DIRS[@]}"; do
        targets+=("${repo_root}/${d}")
    done
fi

for target in "${targets[@]}"; do
    if [ ! -d "${target}" ]; then
        echo "check-js-syntax: not a directory: ${target}" >&2
        exit 2
    fi
done

if ! command -v python3 >/dev/null 2>&1; then
    echo "check-js-syntax: cannot run, python3 is missing" >&2
    exit 2
fi

exec python3 "${repo_root}/scripts/js_syntax_check.py" "${targets[@]}"
