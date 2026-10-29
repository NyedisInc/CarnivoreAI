#!/bin/bash

MUTATE_ROOT=""
MUTATE_FILES=()
MUTATE_BAKDIR=""
MUTATE_CHILD_PID=""
MUTATE_CRASHES=0

mutate_resolve_path() {
    case "$1" in
        /*) echo "$1" ;;
        *)  echo "${MUTATE_ROOT}/$1" ;;
    esac
}

mutate_arm_trap() {
    MUTATE_ROOT="$1"; shift
    MUTATE_FILES=("$@")
    MUTATE_BAKDIR="$(mktemp -d)"
    local i=0 f abs
    for f in "${MUTATE_FILES[@]}"; do
        abs="$(mutate_resolve_path "$f")"
        if [ ! -f "$abs" ]; then
            echo "mutate_arm_trap: no such file: $abs" >&2
            exit 1
        fi
        cp "$abs" "${MUTATE_BAKDIR}/${i}"
        i=$((i + 1))
    done
    trap 'mutate_cleanup 0' EXIT
    trap 'mutate_cleanup 130' INT
    trap 'mutate_cleanup 143' TERM
}

mutate_restore_files() {
    [ -z "$MUTATE_BAKDIR" ] && return 0
    local i=0 f
    for f in "${MUTATE_FILES[@]}"; do
        cp "${MUTATE_BAKDIR}/${i}" "$(mutate_resolve_path "$f")"
        i=$((i + 1))
    done
}

mutate_cleanup() {
    local entry_status=$? exit_code="${1:-0}"
    if [ -n "$MUTATE_CHILD_PID" ]; then
        kill "$MUTATE_CHILD_PID" 2>/dev/null
        MUTATE_CHILD_PID=""
    fi
    mutate_restore_files
    [ -n "$MUTATE_BAKDIR" ] && rm -rf "$MUTATE_BAKDIR"
    MUTATE_BAKDIR=""
    if [ "$exit_code" != "0" ]; then
        trap - EXIT INT TERM
        exit "$exit_code"
    fi
    if [ "$entry_status" = "0" ] && [ "$MUTATE_CRASHES" -gt 0 ]; then
        echo "mutate-trap: ${MUTATE_CRASHES} suite run(s) crashed instead of passing or failing; the result is COULD NOT EVALUATE (exit 2)" >&2
        trap - EXIT
        exit 2
    fi
}

mutate_run() {
    "$@" &
    MUTATE_CHILD_PID=$!
    wait "$MUTATE_CHILD_PID"
    local status=$?
    MUTATE_CHILD_PID=""
    case "$status" in
        0|1) ;;
        *)
            MUTATE_CRASHES=$((MUTATE_CRASHES + 1))
            echo "CANNOT_DETERMINE: the suite exited ${status}, which is a crash or usage error and not a test failure; this mutant was not evaluated"
            ;;
    esac
    return "$status"
}

mutate_baseline() {
    local status
    mutate_restore_files
    mutate_run "$@" >/dev/null 2>&1
    status=$?
    if [ "$status" -ne 0 ]; then
        echo "BASELINE IS RED (suite exited ${status}). Every mutant would read as killed. Refusing to run."
        exit 2
    fi
    echo "baseline green"
}

mutate_isolate_tree() {
    [ -n "${MUTATE_ISOLATED:-}" ] && return 0
    if [ "${MUTATE_IN_PLACE:-}" = "1" ]; then
        echo "mutate-trap: MUTATE_IN_PLACE=1, mutating the live checkout" >&2
        return 0
    fi
    local lib_dir root work py rc
    lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    root="$(cd "${lib_dir}/../../.." && pwd)"
    py="python3"
    [ -x "${root}/venv/bin/python3" ] && py="${root}/venv/bin/python3"
    work="$(mktemp -d "${TMPDIR:-/tmp}/mutate-tree.XXXXXX")" || exit 2
    if ! "$py" "${lib_dir}/isolate_tree.py" "${work}/tree" "$root"; then
        echo "mutate-trap: could not make an isolated copy of the tree; nothing was measured" >&2
        rm -rf "$work"
        exit 2
    fi
    MUTATE_ISOLATED=1 bash "${work}/tree/scripts/ci/$(basename "$0")" "$@"
    rc=$?
    rm -rf "$work"
    exit "$rc"
}
mutate_isolate_tree "$@"
