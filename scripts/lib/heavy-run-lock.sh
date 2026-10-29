#!/usr/bin/env bash

HEAVY_RUN_LOCK_DIR="${CLOUDE_HEAVY_RUN_LOCK_DIR:-$HOME/dev-worktrees/cloudecode/.heavy-run}"
HEAVY_RUN_SLOTS="${CLOUDE_HEAVY_RUN_SLOTS:-1}"
HEAVY_RUN_POLL="${CLOUDE_HEAVY_RUN_POLL:-20}"
HEAVY_RUN_MAX_WAIT="${CLOUDE_HEAVY_RUN_MAX_WAIT:-3600}"
HEAVY_RUN_STALE_SECS="${CLOUDE_HEAVY_RUN_STALE_SECS:-10800}"
HEAVY_RUN_MAX_LOAD="${CLOUDE_HEAVY_RUN_MAX_LOAD:-14}"
HEAVY_RUN_LOAD_MAX_WAIT="${CLOUDE_HEAVY_RUN_LOAD_MAX_WAIT:-1200}"

HEAVY_RUN_ORPHAN_SECS=60

HEAVY_RUN_REPORT_EVERY=300

HEAVY_RUN_HELD=""

heavy_run_log() {
    echo "run-tests.sh: $*" >&2
}

heavy_run_pid_start() {
    LC_ALL=C ps -o lstart= -p "$1" 2>/dev/null | sed 's/^ *//; s/ *$//'
}

heavy_run_field() {
    sed -n "s/^$2=//p" "$1" 2>/dev/null | head -n 1
}

heavy_run_mtime() {
    stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0
}

heavy_run_stale_reason() {
    local slot="$1" owner="$1/owner" now pid want have started
    now="$(date +%s)"
    if [ ! -f "$owner" ]; then
        if [ $((now - $(heavy_run_mtime "$slot"))) -gt "$HEAVY_RUN_ORPHAN_SECS" ]; then
            echo "it has had no owner file for over ${HEAVY_RUN_ORPHAN_SECS} s"
        fi
        return 0
    fi
    pid="$(heavy_run_field "$owner" pid)"
    started="$(heavy_run_field "$owner" started)"
    case "$pid" in ''|*[!0-9]*) echo "its owner file names no pid"; return 0 ;; esac
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "its holder pid $pid is dead"
        return 0
    fi
    want="$(heavy_run_field "$owner" pid_start)"
    have="$(heavy_run_pid_start "$pid")"
    if [ -n "$want" ] && [ "$want" != "$have" ]; then
        echo "pid $pid was reused (started '$have', holder started '$want')"
        return 0
    fi
    case "$started" in ''|*[!0-9]*) started=0 ;; esac
    if [ $((now - started)) -gt "$HEAVY_RUN_STALE_SECS" ]; then
        echo "it is $(( (now - started) / 60 )) min old, over the ${HEAVY_RUN_STALE_SECS} s cap"
    fi
    return 0
}

heavy_run_break() {
    local slot="$1" guard="$1.break" reason
    if ! command mkdir "$guard" 2>/dev/null; then
        if [ $(( $(date +%s) - $(heavy_run_mtime "$guard") )) -gt "$HEAVY_RUN_ORPHAN_SECS" ]; then
            rmdir "$guard" 2>/dev/null
        fi
        return 0
    fi
    reason="$(heavy_run_stale_reason "$slot")"
    if [ -n "$reason" ] && [ -d "$slot" ]; then
        local grave="$slot.stale.$$.$(date +%s)"
        if mv "$slot" "$grave" 2>/dev/null; then
            heavy_run_log "broke heavy-run slot $(basename "$slot"): $reason ($(tr '\n' ' ' < "$grave/owner" 2>/dev/null))"
            rm -rf "$grave"
        fi
    fi
    rmdir "$guard" 2>/dev/null
    return 0
}

heavy_run_describe() {
    local owner="$1/owner" started now
    now="$(date +%s)"
    started="$(heavy_run_field "$owner" started)"
    case "$started" in ''|*[!0-9]*) started="$now" ;; esac
    echo "$(basename "$1") held by pid $(heavy_run_field "$owner" pid)" \
        "(branch $(heavy_run_field "$owner" branch), worktree $(heavy_run_field "$owner" worktree))" \
        "for $(( (now - started) / 60 )) min"
}

heavy_run_try_take() {
    local slot="$1"
    command mkdir "$slot" 2>/dev/null || return 1
    HEAVY_RUN_HELD="$slot"
    {
        echo "pid=$$"
        echo "pid_start=$(heavy_run_pid_start $$)"
        echo "started=$(date +%s)"
        echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "worktree=$2"
        echo "branch=$3"
        echo "host=$(hostname -s 2>/dev/null)"
    } > "$slot/owner.tmp.$$" && mv "$slot/owner.tmp.$$" "$slot/owner"
    return 0
}

heavy_run_acquire() {
    local worktree="$1" branch t0 now i slot busy last_report="" last_at=0 elapsed
    case "$HEAVY_RUN_SLOTS" in ''|*[!0-9]*|0) heavy_run_log "CLOUDE_HEAVY_RUN_SLOTS='$HEAVY_RUN_SLOTS' is not a positive integer"; return 1 ;; esac
    branch="$(git -C "$worktree" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    mkdir -p "$HEAVY_RUN_LOCK_DIR" || return 1
    t0="$(date +%s)"
    while :; do
        busy=""
        i=1
        while [ "$i" -le "$HEAVY_RUN_SLOTS" ]; do
            slot="$HEAVY_RUN_LOCK_DIR/slot-$i.lock"
            if heavy_run_try_take "$slot" "$worktree" "$branch"; then
                heavy_run_log "took heavy-run slot $i of $HEAVY_RUN_SLOTS ($slot)"
                heavy_run_load_gate
                return 0
            fi
            if [ -n "$(heavy_run_stale_reason "$slot")" ]; then
                heavy_run_break "$slot"
                if heavy_run_try_take "$slot" "$worktree" "$branch"; then
                    heavy_run_log "took heavy-run slot $i of $HEAVY_RUN_SLOTS ($slot)"
                    heavy_run_load_gate
                    return 0
                fi
            fi
            busy="$busy; $(heavy_run_describe "$slot")"
            i=$((i + 1))
        done
        now="$(date +%s)"
        elapsed=$((now - t0))
        if [ "$elapsed" -ge "$HEAVY_RUN_MAX_WAIT" ]; then
            heavy_run_log "REFUSED: every heavy-run slot stayed busy for ${elapsed} s${busy}"
            return 1
        fi
        if [ "$busy" != "$last_report" ] || [ $((now - last_at)) -ge "$HEAVY_RUN_REPORT_EVERY" ]; then
            heavy_run_log "waiting for a heavy-run slot (${elapsed}/${HEAVY_RUN_MAX_WAIT} s)${busy}"
            last_report="$busy"
            last_at="$now"
        fi
        sleep "$HEAVY_RUN_POLL"
    done
}

heavy_run_load1() {
    local raw
    raw="$(sysctl -n vm.loadavg 2>/dev/null)"
    if [ -n "$raw" ]; then
        echo "$raw" | awk '{print $2}'
        return 0
    fi
    awk '{print $1}' /proc/loadavg 2>/dev/null
}

heavy_run_load_gate() {
    local t0 load
    t0="$(date +%s)"
    load="$(heavy_run_load1)"
    [ -n "$load" ] || { heavy_run_log "load average unreadable; not gating on it"; return 0; }
    while awk -v l="$load" -v m="$HEAVY_RUN_MAX_LOAD" 'BEGIN { exit !(l > m) }'; do
        if [ $(( $(date +%s) - t0 )) -ge "$HEAVY_RUN_LOAD_MAX_WAIT" ]; then
            heavy_run_log "load $load still over $HEAVY_RUN_MAX_LOAD after ${HEAVY_RUN_LOAD_MAX_WAIT} s; running anyway"
            return 0
        fi
        heavy_run_log "1-minute load $load is over $HEAVY_RUN_MAX_LOAD; waiting"
        sleep "$HEAVY_RUN_POLL"
        load="$(heavy_run_load1)"
    done
    heavy_run_log "starting at 1-minute load $load"
    return 0
}

heavy_run_release() {
    local slot="$HEAVY_RUN_HELD"
    [ -n "$slot" ] || return 0
    HEAVY_RUN_HELD=""
    if [ "$(heavy_run_field "$slot/owner" pid)" = "$$" ] || [ ! -f "$slot/owner" ]; then
        rm -f "$slot/owner" "$slot"/owner.tmp.* 2>/dev/null
        rmdir "$slot" 2>/dev/null
    fi
    return 0
}
