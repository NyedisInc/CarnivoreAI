#!/bin/bash

boot_out_all_carnivore_jobs() {
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  local j
  for j in $(launchctl list | awk '/application\.ai\.carnivore\.menubar/ {print $3}'); do
    log "booting out stray job $j"
    launchctl bootout "gui/$UID/$j" || true
  done
  for _ in $(seq 1 "$POLL_TRIES"); do launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 || break; sleep "$POLL_S"; done
}


pid_alive() {
  local st
  st=$(ps -p "$1" -o stat= 2>/dev/null || true)
  [ -n "$st" ] && [ "${st#Z}" = "$st" ]
}

engine_holder_check() {
  local pid="$1" cmd owner cwd real
  HOLDER_START=""
  cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
  [ -n "$cmd" ] || return 2
  owner=$(ps -p "$pid" -o uid= 2>/dev/null | tr -d ' ' || true)
  cwd=$(lsof -b -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1 || true)
  HOLDER_START=$(ps -p "$pid" -o lstart= 2>/dev/null || true)
  pid_alive "$pid" || return 2
  real=$(cd "$ENGINE_DIR" 2>/dev/null && pwd -P || true)
  case "$cmd" in *" -m src.main"*) ;; *) return 1 ;; esac
  [ "$owner" = "$UID" ] && [ -n "$real" ] && [ "$cwd" = "$real" ] && [ -n "$HOLDER_START" ]
}

port_accepts() {
  local host
  for host in 127.0.0.1 ::1; do
    (exec 3<>"/dev/tcp/$host/$1") 2>/dev/null && return 0
  done
  return 1
}

signal_engines() {
  local pid start rc
  while IFS='|' read -r pid start; do
    [ -n "$pid" ] || continue
    rc=0; engine_holder_check "$pid" || rc=$?
    [ "$rc" != 2 ] || continue
    if [ "$rc" != 0 ] || [ "$HOLDER_START" != "$start" ]; then
      STOP_REFUSAL="pid $pid changed identity before the signal (reused or no longer our engine)"
      log "REFUSED: $STOP_REFUSAL; not signaled"; return 1
    fi
    log "stop the detached engine pid $pid (SIGTERM; tmux sessions untouched)"
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 "$POLL_TRIES"); do pid_alive "$pid" || break; sleep "$POLL_S"; done
    ! pid_alive "$pid" || log "pid $pid ignored SIGTERM; left running for the port wait to refuse"
  done <<< "$1"
}

stop_detached_engine() {
  local port="$1" holders pid rc ours="" foreign=0
  STOP_REFUSAL=""
  holders=$(lsof -b -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
  for pid in $holders; do
    rc=0; engine_holder_check "$pid" || rc=$?
    case "$rc" in
      0) ours="$ours$pid|$HOLDER_START"$'\n' ;;
      2) log "pid $pid left :$port before it could be checked; treating it as stopped" ;;
      *) log "REFUSED: pid $pid holding :$port is not our engine ($(ps -p "$pid" -o comm= 2>/dev/null || true)); not signaled"
         STOP_REFUSAL="a foreign process (pid $pid) holds :$port"; foreign=1 ;;
    esac
  done
  [ "$foreign" = 0 ] || return 1
  if [ -z "$ours" ] && port_accepts "$port"; then
    STOP_REFUSAL=":$port accepts connections but no process of ours holds it (another user's listener?)"
    log "REFUSED: $STOP_REFUSAL; not signaled"; return 1
  fi
  signal_engines "$ours"
}

stop_stray_engines() {
  local pid rc found=""
  for pid in $(pgrep -u "$UID" -f -- "-m src.main" 2>/dev/null || true); do
    rc=0; engine_holder_check "$pid" || rc=$?
    [ "$rc" != 0 ] || found="$found$pid|$HOLDER_START"$'\n'
  done
  signal_engines "$found"
}

wait_for_port_free() {
  local port="$1" holder
  for _ in $(seq 1 "$POLL_TRIES"); do
    holder=$(lsof -b -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)
    [ -z "$holder" ] && return 0
    sleep "$POLL_S"
  done
  holder=$(lsof -b -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)
  log "PORT $port STILL HELD by pid ${holder:-unknown} ($(ps -p "${holder:-0}" -o comm= 2>/dev/null || echo unknown)); refusing to install"
  exit 2
}
