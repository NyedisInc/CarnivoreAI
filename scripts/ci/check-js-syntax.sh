#!/usr/bin/env bash
#
#
#
#
#
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

checked=0
failed=0

check_one() {
    local file="$1" cjs_err
    if cjs_err="$(node --check "${file}" 2>&1)"; then
        return 0
    fi
    if node --input-type=module --check < "${file}" >/dev/null 2>&1; then
        modules=$((modules + 1))
        return 0
    fi
    printf '%s\n' "${cjs_err}" >&2
    return 1
}

modules=0

for target in "${targets[@]}"; do
    while IFS= read -r -d '' file; do
        checked=$((checked + 1))
        if ! check_one "${file}"; then
            echo "check-js-syntax: SYNTAX ERROR in ${file}" >&2
            failed=$((failed + 1))
        fi
    done < <(
        find "${target}" -type f -name '*.js' \
            -not -path '*/node_modules/*' \
            -not -path '*/node_modules.nosync/*' \
            -not -path '*/vendor/*' -print0 | sort -z
    )
done

if [ "${checked}" -eq 0 ]; then
    echo "check-js-syntax: no .js files found under ${targets[*]}" >&2
    exit 2
fi

if [ "${failed}" -gt 0 ]; then
    echo "check-js-syntax: ${failed} of ${checked} file(s) failed to parse" >&2
    exit 1
fi

echo "check-js-syntax: ${checked} file(s) parsed cleanly (${modules} as ES modules)"
exit 0
