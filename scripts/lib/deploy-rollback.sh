#!/bin/bash

bootstrap_with_retries() {
  local i
  for i in 1 2 3 4 5; do
    if launchctl bootstrap "gui/$UID" "$PLIST" 2>"${TMPDIR:-/tmp}/deploy-$TS.boot"; then return 0; fi
    log "bootstrap attempt $i: $(cat "${TMPDIR:-/tmp}/deploy-$TS.boot")"
    sleep 5
  done
  return 1
}

rollback_install() {
  if [ ! -d "$OLD_CONTENTS" ] && [ -d "$OLD/Contents" ]; then OLD_CONTENTS="$OLD/Contents"; fi
  log "ROLLBACK: the install failed; restoring $CUR from $OLD_CONTENTS"
  boot_out_all_carnivore_jobs || true
  stop_detached_engine 8000 || true
  stop_stray_engines || true
  (wait_for_port_free 8000) || true
  if ! python3 -I "$SWAP_HELPER" "$APP/Contents" "$OLD_CONTENTS"; then
    log "ROLLBACK FAILED: could not swap the previous Contents back; they are kept at $OLD_CONTENTS"
    return 1
  fi
  if ! bootstrap_with_retries; then
    log "ROLLBACK: $CUR is back in place but its job did not start; run launchctl bootstrap gui/$UID $PLIST"
    return 1
  fi
  case "$OLD_CONTENTS" in
    "$STAGE"/*) log "ROLLBACK done: $CUR is back and started; the failed install goes with the staging folder" ;;
    *) log "ROLLBACK done: $CUR is back and started; the failed install is kept at $OLD_CONTENTS" ;;
  esac
}

restart_previous_app() {
  log "RESTART: the install stopped before the swap; starting $CUR again"
  if launchctl print "gui/$UID/$LABEL" 2>/dev/null | grep -q 'state = running'; then
    log "RESTART: $LABEL is already running; nothing to start"
    return 0
  fi
  if ! bootstrap_with_retries; then
    log "RESTART: $CUR is intact but its job did not start; run launchctl bootstrap gui/$UID $PLIST"
    return 1
  fi
  log "RESTART done: $CUR is running again"
}

arm_rollback_if_swapped() {
  local now
  now=$(stat -f %i "$APP/Contents" 2>/dev/null) || now=""
  if [ -n "$APP_CONTENTS_INODE" ] && [ -n "$now" ] && [ "$now" != "$APP_CONTENTS_INODE" ] && [ -d "$STAGED_APP/Contents" ]; then
    log "$APP/Contents is no longer the one recorded before the swap: the previous app comes back by rollback, not by restart"
    OLD_CONTENTS="$STAGED_APP/Contents"
    ROLLBACK_ARMED=1
    KEEP_STAGE=1
    OLD_APP_STOPPED=0
  fi
}
