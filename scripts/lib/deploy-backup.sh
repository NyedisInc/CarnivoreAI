#!/bin/bash

backup_database() {
  local name="" f
  for f in carnivore.db cloude.db; do
    if [ -s "$STATE/$f" ]; then name="$f"; break; fi
  done
  if [ -z "$name" ]; then
    log "no database under $STATE to back up"
    return 0
  fi
  mkdir -p "$BACKUP_DIR"
  local quote="'" dest="$BACKUP_DIR/$name"
  sqlite3 "$STATE/$name" "VACUUM INTO '${dest//$quote/$quote$quote}'"
  if [ "$(sqlite3 "$BACKUP_DIR/$name" 'pragma quick_check;')" != ok ]; then
    log "backup check failed"
    exit 2
  fi
}

list_cloude_sessions() {
  local out
  if out=$(tmux -L "${CLOUDE_TMUX_SOCKET:-cloude}" list-sessions \
      -F '#{session_name} #{session_created}' 2>&1); then
    [ -n "$out" ] && printf '%s\n' "$out" | { grep -v '^_carnivore_ctl' || true; } | sort
    return 0
  fi
  case "$out" in
    *"no server running"*|*"error connecting to"*"No such file or directory"*) return 0 ;;
  esac
  log "tmux list-sessions failed: $out" >&2
  return 2
}

snapshot_sessions_before() {
  list_cloude_sessions > "${TMPDIR:-/tmp}/deploy-$TS.before" || exit 2
  wc -l < "${TMPDIR:-/tmp}/deploy-$TS.before"
}
