#!/usr/bin/env bash
#
#
set -u

DB="${PACK_WAIT_DB:-${CARNIVORE_STATE_DIR:-$HOME/Library/Application Support/Carnivore}/carnivore.db}"
POLL="${PACK_WAIT_POLL:-10}"
MAX="${PACK_WAIT_MAX:-900}"

count_ops() {
    command -v sqlite3 >/dev/null 2>&1 || return 1
    [ -f "$DB" ] || return 1
    sqlite3 -readonly -cmd '.timeout 3000' "$DB" \
        "SELECT (SELECT COUNT(*) FROM pack_session_moves WHERE role='source' AND state NOT IN ('moved','failed')) + (SELECT COUNT(*) FROM pack_migrations WHERE role='source' AND state IN ('applying','verifying'));" 2>/dev/null
}

waited=0
while :; do
    n="$(count_ops)" || n=""
    case "$n" in
        ''|*[!0-9]*) echo "pack-ops: could not determine whether a Pack transfer is in flight ($DB), restarting without waiting"; exit 0 ;;
    esac
    [ "$n" -eq 0 ] && exit 0
    if [ "$waited" -ge "$MAX" ]; then
        echo "pack-ops: WARNING: $n Pack transfer(s) still in flight after ${MAX}s, restarting anyway; they will be marked interrupted"
        exit 0
    fi
    echo "pack-ops: waiting for $n in-flight Pack transfer(s) to finish before the restart (${waited}s of ${MAX}s)"
    sleep "$POLL"
    waited=$((waited + POLL))
done
