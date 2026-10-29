#!/bin/bash

mutate_web_available() {
    local root="$1"
    if ! command -v node >/dev/null 2>&1; then
        echo "mutate_web: node is not on PATH" >&2
        return 1
    fi
    if [ ! -d "${root}/web" ]; then
        echo "mutate_web: no web/ directory at ${root}/web" >&2
        return 1
    fi
    if [ ! -x "${root}/web/node_modules/.bin/vitest" ]; then
        echo "mutate_web: vitest is not installed - run 'cd web && npm ci'" >&2
        return 1
    fi
    return 0
}

mutate_web_require() {
    local root="$1"
    if ! mutate_web_available "$root"; then
        echo "CANNOT EVALUATE the client half. Nothing was proven about it." >&2
        echo "2 IS NOT 0 - this is not a pass." >&2
        exit 2
    fi
}

mutate_web_run() {
    local root="$1" file="$2"
    local rel="${file#web/}"
    ( cd "${root}/web" && exec ./node_modules/.bin/vitest run --reporter=dot "$rel" ) \
        >/dev/null 2>&1 &
    MUTATE_CHILD_PID=$!
    wait "$MUTATE_CHILD_PID"
    local rc=$?
    MUTATE_CHILD_PID=""
    return "$rc"
}

mutate_web_files_exist() {
    local root="$1"; shift
    local f missing=0
    for f in "$@"; do
        if [ ! -f "${root}/${f}" ]; then
            echo "mutate_web: named vitest file does not exist: ${f}" >&2
            missing=1
        fi
    done
    if [ "$missing" -ne 0 ]; then
        echo "CANNOT EVALUATE - a suite this script scores against is missing." >&2
        echo "2 IS NOT 0 - this is not a pass." >&2
        exit 2
    fi
}
