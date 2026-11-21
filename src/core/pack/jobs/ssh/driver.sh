
CVJ_ROOT=${CVJ_ROOT:-}; CVJ_UID=${CVJ_UID:-}; CVJ_NAME=${CVJ_NAME:-}; CVJ_JOB=${CVJ_JOB:-}
CVJ_SLOT=${CVJ_SLOT:-}; CVJ_SLOTS=${CVJ_SLOTS:-3}; CVJ_COMMIT=${CVJ_COMMIT:-}; CVJ_BLOB=${CVJ_BLOB:-}
CVJ_CAP=${CVJ_CAP:-}; CVJ_CALLER=${CVJ_CALLER:-}; CVJ_EST=${CVJ_EST:-}; CVJ_SIZE=${CVJ_SIZE:-}
CVJ_SHA256=${CVJ_SHA256:-}; CVJ_KEEP=${CVJ_KEEP:-0}; CVJ_MEMO=${CVJ_MEMO:-}; CVJ_COMMAND=${CVJ_COMMAND:-}
CVJ_ENV_SH=${CVJ_ENV_SH:-}; CVJ_STEPS_SH=${CVJ_STEPS_SH:-}; CVJ_RUN_SH=${CVJ_RUN_SH:-}
CVJ_DONE=; CVJ_LOCKED=
HOME=${HOME:-}

cvj_say() { printf 'CVJ%s %s\n' "$CVJ_NONCE" "$1"; }
cvj_end() { CVJ_DONE=1; printf 'CVJ%s end %s\n' "$CVJ_NONCE" "$1"; if [ -n "$CVJ_LOCKED" ]; then exit 90; fi; exit "$1"; }
cvj_fail() { cvj_say "error $1 $2"; cvj_end 1; }
cvj_trap() { if [ -z "$CVJ_DONE" ]; then printf 'CVJ%s end 70\n' "$CVJ_NONCE"; fi; }
trap cvj_trap EXIT

cvj_synced() {
  case "$1" in
    /mnt/*|*[Dd]ropbox*|*[Oo]ne[Dd]rive*|*[Ii]cloud*|*"Mobile Documents"*) return 1 ;;
  esac
  return 0
}

cvj_setup() {
  R=$CVJ_ROOT
  if [ -z "$R" ]; then
    [ -n "$HOME" ] || cvj_fail bad_far_root "there is no home folder"
    R="$HOME/.carnivore-ssh-jobs"
  fi
  case "$R" in /*) ;; *) cvj_fail bad_far_root "the far root is not an absolute path" ;; esac
  cvj_synced "$R" || cvj_fail bad_far_root "the far root is on a windows mount or a synced folder"
  case "/$R/" in */../*) cvj_fail bad_far_root "the far root holds a .. part" ;; esac
  if [ -d "$R" ]; then
    [ -f "$R/.carnivore-ssh-jobs" ] || cvj_fail bad_far_root "the far root exists and is not one of ours"
  else
    mkdir -p "$R" || cvj_fail bad_far_root "the far root cannot be created"
    : > "$R/.carnivore-ssh-jobs" || cvj_fail bad_far_root "the far root cannot be marked"
  fi
  chmod 700 "$R" || cvj_fail bad_far_root "the far root cannot be locked down"
  P=$(cd -P "$R" && pwd -P) || cvj_fail bad_far_root "the far root cannot be entered"
  cvj_synced "$P" || cvj_fail bad_far_root "the far root resolves onto a windows mount or a synced folder"
  mkdir -p "$P/repos" "$P/folders" "$P/meta" "$P/in" "$P/out" || cvj_fail bad_far_root "the far root cannot be filled"
  : >> "$P/lock" || cvj_fail bad_far_root "the lock file cannot be made"
  CVJ_KILLBIN=
  if [ -x /usr/bin/kill ]; then CVJ_KILLBIN=/usr/bin/kill; elif [ -x /bin/kill ]; then CVJ_KILLBIN=/bin/kill; fi
}

cvj_with_lock() {
  ( CVJ_LOCKED=1
    if ! flock -x -w 30 9; then cvj_say "error lock_busy another call holds the far lock"; cvj_end 1; fi
    "$@" ) 9>>"$P/lock" || cvj_lockfail "$?"
}
cvj_lockfail() {
  if [ "$1" -eq 90 ]; then CVJ_DONE=1; exit 1; fi
  cvj_say "error internal the far driver failed"; cvj_end 1
}

cvj_sha() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1; fi
}

cvj_ident() {
  [ -r "/proc/$1/stat" ] || return 0
  sed 's/^.*) //' "/proc/$1/stat" 2>/dev/null | cut -d ' ' -f 20
}
cvj_mine() {
  CVJ_PID=$(head -c 20 "$1" 2>/dev/null || true)
  case "$CVJ_PID" in ''|*[!0-9]*) return 1 ;; esac
  [ "$CVJ_PID" -gt 1 ] || return 1
  kill -0 "$CVJ_PID" 2>/dev/null || return 1
  if [ -r /proc/sys/kernel/random/boot_id ] && [ -f "$3/boot" ]; then
    [ "$(cat /proc/sys/kernel/random/boot_id)" = "$(head -c 64 "$3/boot")" ] || return 1
  fi
  if [ -f "$2" ] && [ -r "/proc/$CVJ_PID/stat" ]; then
    [ "$(cvj_ident "$CVJ_PID")" = "$(head -c 40 "$2")" ] || return 1
  fi
  return 0
}
cvj_alive() {
  [ ! -e "$1/exit" ] || return 1
  [ -f "$1/pid" ] || return 1
  cvj_mine "$1/pid" "$1/pidid" "$1"
}

cvj_extras() {
  for d in /usr/lib/wsl/lib "$HOME/.local/bin" /usr/local/cuda/bin; do
    if [ -d "$d" ]; then printf '%s\n' "$d"; fi
  done
  n=$(ls -dt "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | head -n 1 || true)
  if [ -n "$n" ]; then printf '%s\n' "$n"; fi
  return 0
}
cvj_jobpath() {
  cvj_extras | { jp=$PATH
    while IFS= read -r d; do
      case ":$jp:" in *":$d:"*) ;; *) jp="$jp:$d" ;; esac
    done
    printf '%s' "$jp"; }
}
cvj_tmo() { if command -v timeout >/dev/null 2>&1; then timeout 5 "$@"; else "$@"; fi; }
cvj_nvsmi() {
  g=$(command -v nvidia-smi 2>/dev/null || true)
  if [ -z "$g" ] && [ -x /usr/lib/wsl/lib/nvidia-smi ]; then g=/usr/lib/wsl/lib/nvidia-smi; fi
  printf '%s' "$g"
}

cvj_gitok() {
  v=$(git --version 2>/dev/null || true); v=${v#git version }
  maj=${v%%.*}; rest=${v#*.}; min=${rest%%.*}
  case "$maj" in ''|*[!0-9]*) return 1 ;; esac
  min=${min%%[!0-9]*}; if [ -z "$min" ]; then min=0; fi
  [ "$maj" -gt 2 ] || { [ "$maj" -eq 2 ] && [ "$min" -ge 31 ]; }
}

cvj_hello() {
  cvj_setup
  cvj_say "root $P"
  cvj_say "uname $(uname -s) $(uname -r) $(uname -m)"
  if grep -qi microsoft /proc/version 2>/dev/null; then cvj_say "wsl 1"; else cvj_say "wsl 0"; fi
  gv=$(git --version 2>/dev/null || true); cvj_say "git ${gv#git version }"
  missing=""
  if ! cvj_gitok; then missing="git"; fi
  for t in setsid flock timeout; do
    p=$(command -v "$t" 2>/dev/null || true); cvj_say "tool $t ${p:--}"
    if [ -z "$p" ] && [ "$t" != timeout ]; then missing="$missing $t"; fi
  done
  cvj_say "tool kill ${CVJ_KILLBIN:--}"
  if [ -z "$CVJ_KILLBIN" ]; then missing="$missing kill"; fi
  sp=$(command -v sha256sum 2>/dev/null || command -v shasum 2>/dev/null || true); cvj_say "tool sha256 ${sp:--}"
  if [ -z "$sp" ]; then missing="$missing sha256"; fi
  cvj_say "path $PATH"
  cvj_extras | while IFS= read -r d; do cvj_say "extra $d"; done
  for d in "$P"/meta/*; do
    if [ -d "$d" ] && cvj_alive "$d"; then
      cvj_say "job ${d##*/} $(head -c 64 "$d/caller" 2>/dev/null || true) $(head -c 12 "$d/est" 2>/dev/null || true)"
    fi
  done
  if [ -n "$missing" ]; then
    m=$(printf '%s' "$missing" | tr -s ' ' ',' | sed 's/^,//')
    cvj_fail missing_tools "$m"
  fi
}

cvj_probe() {
  cvj_setup
  cvj_say "uname $(uname -s) $(uname -r) $(uname -m)"
  n=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0); cvj_say "cores $n"
  if [ -r /proc/meminfo ]; then cvj_say "memtotal_kb $(awk '/^MemTotal/ {print $2}' /proc/meminfo)"; fi
  cvj_say "disk_free_kb $(df -Pk "$P" | awk 'NR==2 {print $4}')"
  g=$(cvj_nvsmi)
  if [ -n "$g" ]; then
    cvj_tmo "$g" --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 8 | while IFS= read -r l; do cvj_say "gpu $l"; done || true
  fi
  jp=$(cvj_jobpath)
  for t in git node npm python3 python3.12 pip3 uv tmux gcc make cargo go gh docker claude codex ffmpeg ffprobe blender playwright; do
    p=$(PATH="$jp" command -v "$t" 2>/dev/null || true)
    if [ -n "$p" ]; then cvj_say "tool $t $p"; fi
  done
  for d in "$HOME"/.cache/ms-playwright/*; do
    if [ -e "$d" ]; then cvj_say "playwright ${d##*/}"; fi
  done
}

cvj_pressure() {
  cvj_setup
  n=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0); cvj_say "cores $n"
  if [ -r /proc/loadavg ]; then cvj_say "loadavg $(head -n 1 /proc/loadavg)"; fi
  if [ -r /proc/stat ]; then cvj_say "stat $(head -n 1 /proc/stat)"; fi
  if [ -r /proc/pressure/memory ]; then
    cvj_say "psi_mem $(sed -n 1p /proc/pressure/memory)"; cvj_say "psi_mem $(sed -n 2p /proc/pressure/memory)"
  fi
  cvj_say "disk_free_kb $(df -Pk "$P" | awk 'NR==2 {print $4}')"
  if [ -r /proc/meminfo ]; then cvj_say "memavail_kb $(awk '/^MemAvailable/ {print $2}' /proc/meminfo)"; fi
  g=$(cvj_nvsmi)
  if [ -n "$g" ]; then
    cvj_tmo "$g" --query-gpu=utilization.gpu,memory.free --format=csv,noheader,nounits 2>/dev/null | head -n 8 | while IFS= read -r l; do cvj_say "gpu $l"; done || true
  fi
}

cvj_folder() {
  CACHE="$P/repos/$CVJ_UID.git"
  FD="$P/folders/$CVJ_NAME-$(printf '%.8s' "$CVJ_UID")"
}

cvj_claim_body() {
  if [ ! -d "$CACHE" ]; then git init --bare -q "$CACHE" || cvj_fail git_failed "the folder cache cannot be made"; fi
  mkdir -p "$FD" || cvj_fail git_failed "the project folder cannot be made"
  got=""; n=1
  while [ "$n" -le "$CVJ_SLOTS" ]; do
    if [ -f "$FD/slot$n.job" ] && [ "$(head -c 80 "$FD/slot$n.job")" = "$CVJ_JOB" ]; then got=$n; break; fi
    n=$((n + 1))
  done
  n=1
  while [ -z "$got" ] && [ "$n" -le "$CVJ_SLOTS" ]; do
    free=0
    if [ -e "$FD/slot$n.keep" ]; then free=0
    elif [ ! -f "$FD/slot$n.job" ]; then free=1
    else
      j=$(head -c 80 "$FD/slot$n.job")
      if [ ! -d "$P/meta/$j" ] && [ -n "$(find "$FD/slot$n.job" -mmin +60 -print 2>/dev/null)" ]; then free=1; fi
    fi
    if [ "$free" -eq 1 ]; then got=$n; fi
    n=$((n + 1))
  done
  if [ -z "$got" ]; then cvj_fail no_free_slot "all folders of this project are busy"; fi
  printf '%s\n' "$CVJ_JOB" > "$FD/slot$got.job" || cvj_fail git_failed "the folder claim cannot be written"
  cvj_say "slot $got"
  if [ -f "$FD/slot$got.memo" ]; then cvj_say "memo $(head -c 256 "$FD/slot$got.memo" | tr -d '\r\n')"; fi
}
cvj_claim() { cvj_setup; cvj_folder; cvj_with_lock cvj_claim_body; }

cvj_start_body() {
  M="$P/meta/$CVJ_JOB"
  if [ -e "$M" ]; then cvj_fail job_exists "this job id already has a folder"; fi
  if [ ! -f "$FD/slot$CVJ_SLOT.job" ] || [ "$(head -c 80 "$FD/slot$CVJ_SLOT.job")" != "$CVJ_JOB" ]; then
    cvj_fail slot_not_claimed "the folder was not claimed by this job"
  fi
  if [ -n "$CVJ_BLOB" ]; then
    B="$P/in/$CVJ_BLOB.bundle"
    [ -f "$B" ] || cvj_fail no_bundle "the bundle was not uploaded"
    git -C "$CACHE" bundle verify "$B" >/dev/null 2>&1 || cvj_fail bundle_unverified "the bundle does not verify against the cache"
  else
    git -C "$CACHE" cat-file -e "$CVJ_COMMIT^{commit}" 2>/dev/null || cvj_fail bundle_unverified "the cache does not hold the commit"
  fi
  mkdir "$M" || cvj_fail start_failed "the job folder cannot be made"
  printf '%s' "$CVJ_COMMAND" > "$M/command.sh"
  printf '%s' "$CVJ_ENV_SH" > "$M/env.sh"
  printf '%s' "$CVJ_STEPS_SH" > "$M/steps.sh"
  printf '%s' "$CVJ_RUN_SH" > "$M/run.sh"
  printf '%s' "$CVJ_MEMO" > "$M/memo.in"
  printf '%s\n' "$CVJ_CALLER" > "$M/caller"
  printf '%s\n' "$CVJ_EST" > "$M/est"
  printf '%s' "$(cvj_jobpath)" > "$M/path"
  printf "JOB='%s'\nNAME='%s'\nUID_='%s'\nSLOT='%s'\nCOMMIT='%s'\nBLOB='%s'\nCAP='%s'\n" \
    "$CVJ_JOB" "$CVJ_NAME" "$CVJ_UID" "$CVJ_SLOT" "$CVJ_COMMIT" "$CVJ_BLOB" "$CVJ_CAP" > "$M/job.conf"
  : > "$M/output.log"
  echo preparing > "$M/phase"
  chmod 600 "$M/command.sh" "$M/env.sh" "$M/steps.sh" "$M/job.conf"
  setsid -f /bin/sh "$M/run.sh" "$P" "$CVJ_JOB" </dev/null >/dev/null 2>&1 9>&-
  i=0
  while [ ! -f "$M/pid" ] && [ "$i" -lt 25 ]; do sleep 0.2; i=$((i + 1)); done
  if [ ! -f "$M/pid" ]; then cvj_fail start_failed "the job did not start"; fi
  cvj_say "pid $(head -c 20 "$M/pid")"
}
cvj_start() { cvj_setup; cvj_folder; cvj_with_lock cvj_start_body; }

cvj_meta() {
  M="$P/meta/$CVJ_JOB"
  [ -d "$M" ] || cvj_fail no_such_job "there is no such job here"
}

cvj_status() {
  cvj_setup; cvj_meta
  if [ -f "$M/exit" ]; then
    cvj_say "state exited"; cvj_say "code $(head -c 12 "$M/exit" | tr -d '\r\n')"
  elif cvj_alive "$M"; then
    cvj_say "state $(head -c 20 "$M/phase" 2>/dev/null | tr -d '\r\n' || true)"
  else
    cvj_say "state lost"
  fi
  if [ -f "$M/reason" ]; then cvj_say "reason $(head -c 256 "$M/reason" | tr -d '\r\n')"; fi
  cvj_say "size $(wc -c < "$M/output.log" | tr -d ' ')"
  tail -c 16384 "$M/output.log" | tail -n 300 | tr -d '\r' | fold -w 200 | while IFS= read -r l; do cvj_say "out $l"; done || true
}

cvj_collect() {
  cvj_setup; cvj_meta
  [ -f "$M/exit" ] || cvj_fail not_finished "the job has not finished"
  cvj_say "exit $(head -c 12 "$M/exit" | tr -d '\r\n')"
  if [ -f "$M/result" ]; then
    while read -r k v; do
      case "$k" in commit|changed) cvj_say "$k $v" ;; esac
    done < "$M/result"
  fi
  if [ -f "$P/out/$CVJ_JOB.bundle" ]; then
    cvj_say "size $(wc -c < "$P/out/$CVJ_JOB.bundle" | tr -d ' ')"
    cvj_say "sha256 $(cvj_sha "$P/out/$CVJ_JOB.bundle")"
  fi
}

cvj_group() {
  if [ -n "$CVJ_KILLBIN" ] && [ -n "$2" ]; then "$CVJ_KILLBIN" -s "$1" -- "-$2" 2>/dev/null || true; fi
}
cvj_stop() {
  cvj_setup; cvj_meta
  if [ -f "$M/exit" ]; then cvj_say "stopped already"; return 0; fi
  : > "$M/stopped"
  pid=; cp=
  if cvj_mine "$M/pid" "$M/pidid" "$M"; then pid=$CVJ_PID; fi
  if cvj_mine "$M/cpid" "$M/cpidid" "$M"; then cp=$CVJ_PID; fi
  if [ -n "$cp" ]; then cvj_group TERM "$cp"; elif [ -n "$pid" ]; then cvj_group TERM "$pid"; fi
  i=0
  while cvj_alive "$M" && [ "$i" -lt 20 ]; do sleep 0.5; i=$((i + 1)); done
  if cvj_alive "$M"; then
    cvj_group KILL "$cp"; cvj_group KILL "$pid"; sleep 1
  fi
  if [ ! -f "$M/exit" ]; then
    echo "stopped by the owner" > "$M/reason"; echo 143 > "$M/exit.tmp"; mv -f "$M/exit.tmp" "$M/exit"
  fi
  cvj_say "stopped"
}

cvj_release_body() {
  M="$P/meta/$CVJ_JOB"
  if [ -d "$M" ]; then
    if cvj_alive "$M"; then cvj_fail still_running "the job is still running"; fi
    NAME=; UID_=; SLOT=; BLOB=
    . "$M/job.conf"
    CVJ_UID=$UID_; CVJ_NAME=$NAME; cvj_folder
    git -C "$CACHE" for-each-ref --format='%(refname)' "refs/carnivore/jobs/$CVJ_JOB/" 2>/dev/null \
      | while IFS= read -r r; do git -C "$CACHE" update-ref -d "$r" || true; done || true
    if [ -n "$BLOB" ]; then rm -f "$P/in/$BLOB.bundle" "$P/in/$BLOB.part"; fi
    rm -f "$P/out/$CVJ_JOB.bundle" "$P/out/$CVJ_JOB.tmp"
    if [ -f "$FD/slot$SLOT.job" ] && [ "$(head -c 80 "$FD/slot$SLOT.job")" = "$CVJ_JOB" ]; then
      rm -f "$FD/slot$SLOT.job"
      if [ "$CVJ_KEEP" = 1 ]; then : > "$FD/slot$SLOT.keep"; fi
    fi
    rm -rf "$M"
  fi
  cvj_say "released"
}
cvj_release() { cvj_setup; cvj_with_lock cvj_release_body; }

cvj_sweep_body() {
  n=0
  for d in "$P"/meta/*; do
    [ -d "$d" ] || continue
    if [ -n "$(find "$d" -prune -mtime +7 -print)" ] && ! cvj_alive "$d"; then
      rm -rf "$d"; rm -f "$P/out/${d##*/}.bundle" "$P/out/${d##*/}.tmp"; n=$((n + 1))
    fi
  done
  find "$P/in" "$P/out" -type f -mtime +7 -exec rm -f {} + 2>/dev/null || true
  cvj_say "swept $n"
}
cvj_sweep() { cvj_setup; cvj_with_lock cvj_sweep_body; }

cvj_forget_body() {
  kept=0
  U8=$(printf '%.8s' "$CVJ_UID")
  for FD in "$P"/folders/*-"$U8"; do
    [ -d "$FD" ] || continue
    for d in "$FD"/slot*.job; do
      [ -f "$d" ] || continue
      if cvj_alive "$P/meta/$(head -c 80 "$d")"; then cvj_fail still_running "a job of this project is still running"; fi
    done
  done
  for FD in "$P"/folders/*-"$U8"; do
    [ -d "$FD" ] || continue
    for s in "$FD"/slot[0-9]; do
      [ -e "$s" ] || continue
      if [ -e "$s.keep" ]; then cvj_say "kept $s"; kept=1; continue; fi
      rm -rf "$s" "$s.job" "$s.memo"
    done
    rm -f "$FD"/slot*.job || cvj_fail git_failed "the claims cannot be removed"
    rmdir "$FD" 2>/dev/null || true
  done
  if [ "$kept" -eq 0 ]; then
    rm -rf "$CACHE"
  else
    cvj_say "cache_kept 1"
  fi
  cvj_say "forgotten"
}
cvj_forget() { cvj_setup; cvj_folder; cvj_with_lock cvj_forget_body; }

cvj_seal() {
  cvj_setup
  f="$P/in/$CVJ_BLOB.part"
  [ -f "$f" ] || cvj_fail no_upload "there is no upload to seal"
  sz=$(wc -c < "$f" | tr -d ' ')
  [ "$sz" = "$CVJ_SIZE" ] || cvj_fail bad_upload "the upload size does not match"
  [ "$(cvj_sha "$f")" = "$CVJ_SHA256" ] || cvj_fail bad_upload "the upload hash does not match"
  mv -f "$f" "$P/in/$CVJ_BLOB.bundle" || cvj_fail bad_upload "the upload cannot be sealed"
  cvj_say "sealed $sz"
}

cvj_main() {
  case "$CVJ_VERB" in
    hello) cvj_hello ;;
    probe) cvj_probe ;;
    pressure) cvj_pressure ;;
    claim) cvj_claim ;;
    start) cvj_start ;;
    status) cvj_status ;;
    collect) cvj_collect ;;
    stop) cvj_stop ;;
    release) cvj_release ;;
    sweep) cvj_sweep ;;
    forget) cvj_forget ;;
    seal) cvj_seal ;;
    *) cvj_fail bad_verb "unknown verb" ;;
  esac
  cvj_end 0
}
cvj_main </dev/null
