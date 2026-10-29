#!/bin/bash
#
#
#
#
#

MUTATE_ROOT=""
MUTATE_FILES=()
MUTATE_BAKDIR=""
MUTATE_CHILD_PID=""

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
    local exit_code="${1:-0}"
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
}

mutate_run() {
    "$@" &
    MUTATE_CHILD_PID=$!
    wait "$MUTATE_CHILD_PID"
    local status=$?
    MUTATE_CHILD_PID=""
    return "$status"
}
