#!/usr/bin/env bash

APP="/Applications/Carnivore.app"
LOGIN_LABELS="ai.carnivore.menubar com.cloudecode.menubar ai.carnivore.install-launch"
APP_PATTERN="^/Applications/Carnivore.app/Contents/(MacOS|Frameworks)/"
KEYCHAIN_SERVICES="ai.carnivore.federation.key ai.carnivore.relay.device-key ai.carnivore.relay.legacy-publish-token ai.carnivore.catalog.guest-key carnivore-byoai carnivore-notifications carnivore-messaging carnivore-native-push carnivore-summary-api carnivore-summary-local"
KEYCHAIN_BOUND=100
ASSUME_YES=0
DRY_RUN=0
STOP_TMUX=0
TMUX_BIN_GIVEN=""
PATHS=()
CPLUG_SERVICES=()
TTY_DEV=/dev/tty

CONTRACT_APP="/Applications/Carnivore.app"
CONTRACT_SERVICE_LABEL="ai.carnivore.menubar.engine"
CONTRACT_AGENT_LABELS="ai.carnivore.menubar com.cloudecode.menubar"
CONTRACT_TCC_BUNDLE_IDS="ai.carnivore.menubar com.cloudecode.menubar"
CONTRACT_TCC_SERVICES="AppleEvents SystemPolicyAllFiles SystemPolicyAppData SystemPolicyDocumentsFolder SystemPolicyDesktopFolder SystemPolicyDownloadsFolder SystemPolicyRemovableVolumes SystemPolicyNetworkVolumes"
CONTRACT_TMUX_SOCKETS="cloude carnivore"
CONTRACT_MIN_APP_VERSION="1.16.4"

contract_say() {
  printf '%s\n' "$*"
}

contract_find_bundle() {
  local home="${CONTRACT_HOME:-$HOME}" launchctl_bin="${CONTRACT_LAUNCHCTL:-launchctl}" program candidate
  program="$("$launchctl_bin" print "gui/$(id -u)/$CONTRACT_SERVICE_LABEL" </dev/null 2>/dev/null | sed -n 's/^[[:space:]]*program = //p' | head -n 1)"
  case "$program" in
    */Contents/MacOS/Carnivore)
      if [[ -x "$program" ]]; then printf '%s\n' "${program%/Contents/MacOS/Carnivore}"; return 0; fi
      ;;
  esac
  for candidate in "$CONTRACT_APP" "$home/Applications/Carnivore.app" "$home"/.Trash/Carnivore*.app; do
    if [[ -x "$candidate/Contents/MacOS/Carnivore" ]]; then printf '%s\n' "$candidate"; return 0; fi
  done
  return 0
}

contract_app_bin() {
  local bundle
  bundle="$(contract_find_bundle)"
  if [[ -n "$bundle" ]]; then printf '%s\n' "$bundle/Contents/MacOS/Carnivore"; fi
  return 0
}

contract_app_version() {
  sed -n '/<key>CFBundleShortVersionString<\/key>/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "$1/Contents/Info.plist" 2>/dev/null | head -n 1
  return 0
}

contract_version_at_least() {
  local -a have want
  local i x y
  IFS=. read -r -a have <<<"${1%%[-+]*}"
  IFS=. read -r -a want <<<"$2"
  for i in 0 1 2; do
    x="${have[i]:-0}"
    y="${want[i]:-0}"
    [[ "$x" =~ ^[0-9]+$ && "$y" =~ ^[0-9]+$ ]] || return 1
    if ((10#$x > 10#$y)); then return 0; fi
    if ((10#$x < 10#$y)); then return 1; fi
  done
  return 0
}

contract_service_registered() {
  local home="${CONTRACT_HOME:-$HOME}" launchctl_bin="${CONTRACT_LAUNCHCTL:-launchctl}"
  if "$launchctl_bin" print "gui/$(id -u)/$CONTRACT_SERVICE_LABEL" </dev/null >/dev/null 2>&1; then return 0; fi
  grep -q 'launchd-agent' "$home/Library/Application Support/Carnivore Menubar/engine-host.json" 2>/dev/null
}

contract_run_bounded() {
  local limit="$1" pid i=0 rc=0
  shift
  "$@" </dev/null 2>/dev/null &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [[ "$i" -ge "$limit" ]]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 1
    i=$((i + 1))
  done
  wait "$pid" || rc=$?
  return "$rc"
}

contract_unregister_login_service() {
  local mode="$1" bin bundle version uid launchctl_bin rc=0
  uid="$(id -u)"
  launchctl_bin="${CONTRACT_LAUNCHCTL:-launchctl}"
  bin=""
  if [[ "${CONTRACT_SYSTEM:-1}" == 1 ]]; then bin="$(contract_app_bin)"; fi
  bundle="${bin%/Contents/MacOS/Carnivore}"
  version=""
  if [[ -n "$bin" ]]; then version="$(contract_app_version "$bundle")"; fi
  if [[ "${CONTRACT_SYSTEM:-1}" != 1 ]]; then
    contract_say "login service: the installed app is not run from here, booting out $CONTRACT_SERVICE_LABEL with launchctl"
  elif [[ -z "$bin" ]]; then
    contract_say "login service: no Carnivore app found, booting out $CONTRACT_SERVICE_LABEL with launchctl"
  elif ! contract_service_registered; then
    contract_say "login service: no engine login job is registered, so the app is not run"
  elif ! contract_version_at_least "$version" "$CONTRACT_MIN_APP_VERSION"; then
    contract_say "login service: this app (version ${version:-unknown}) cannot unregister it; booting out $CONTRACT_SERVICE_LABEL with launchctl, and macOS may start it again at the next login"
  elif [[ "$mode" == dry ]]; then
    contract_say "[dry-run] would run: $bin --unregister-login-service"
  else
    contract_run_bounded 30 "$bin" --unregister-login-service || rc=$?
    if [[ "$rc" == 0 ]]; then
      contract_say "login service: the app unregistered it"
    else
      contract_say "login service: the app could NOT unregister it (exit $rc, 124 is a timeout); it is booted out for now and macOS may start it again at the next login. Remove it in System Settings, General, Login Items & Extensions"
    fi
  fi
  if [[ "$mode" == dry ]]; then
    contract_say "[dry-run] would run: launchctl bootout gui/$uid/$CONTRACT_SERVICE_LABEL"
  else
    "$launchctl_bin" bootout "gui/$uid/$CONTRACT_SERVICE_LABEL" </dev/null >/dev/null 2>&1 || true
  fi
}

contract_unregister_agents() {
  local mode="$1" label uid home launchctl_bin
  uid="$(id -u)"
  home="${CONTRACT_HOME:-$HOME}"
  launchctl_bin="${CONTRACT_LAUNCHCTL:-launchctl}"
  for label in $CONTRACT_AGENT_LABELS; do
    if [[ "$mode" == dry ]]; then
      contract_say "[dry-run] would run: launchctl bootout gui/$uid/$label"
    else
      "$launchctl_bin" bootout "gui/$uid/$label" </dev/null >/dev/null 2>&1 || true
    fi
  done
  for label in $CONTRACT_AGENT_LABELS; do
    if [[ "$mode" == dry ]]; then
      contract_say "[dry-run] would remove: $home/Library/LaunchAgents/$label.plist"
    else
      rm -f "${home:?}/Library/LaunchAgents/$label.plist"
    fi
  done
}

contract_launchd_left() {
  local label launchctl_bin="${CONTRACT_LAUNCHCTL:-launchctl}"
  if [[ "${CONTRACT_SYSTEM:-1}" != 1 ]]; then return 0; fi
  for label in "$CONTRACT_SERVICE_LABEL" $CONTRACT_AGENT_LABELS; do
    if "$launchctl_bin" print "gui/$(id -u)/$label" </dev/null >/dev/null 2>&1; then printf '%s\n' "$label"; fi
  done
  return 0
}

contract_record_background_items() {
  local out="" lines
  if [[ "${CONTRACT_SYSTEM:-1}" != 1 ]] || ! command -v sfltool >/dev/null 2>&1; then
    contract_say "background items: not checked (sfltool is not available here)"
    return 0
  fi
  if [[ "$(id -u)" != 0 ]]; then
    contract_say "background items: not checked (macOS lets only root read the list). To see whether a Carnivore record remains, run: sudo sfltool dumpbtm"
    return 0
  fi
  out="$(contract_run_bounded 20 sfltool dumpbtm)" || true
  lines="$(printf '%s\n' "$out" | grep -i -E 'carnivore|cloudecode' || true)"
  if [[ -n "$lines" ]]; then
    contract_say "background items: macOS still lists a Carnivore record. The login service is unregistered; the record is macOS's own"
    contract_say "  and goes away when you remove it in System Settings, General, Login Items & Extensions."
    printf '%s\n' "$lines" | head -n 12 | sed 's/^/  /'
  elif printf '%s\n' "$out" | grep -q 'Records for UID'; then
    contract_say "background items: no Carnivore record"
  else
    contract_say "background items: could not read the list, so a record may remain (run: sudo sfltool dumpbtm)"
  fi
}

contract_reset_tcc() {
  local mode="$1" id service ok refused
  if [[ "${CONTRACT_SYSTEM:-1}" != 1 ]] || ! command -v tccutil >/dev/null 2>&1; then
    contract_say "privacy rows: not reset (tccutil is not available here)"
    return 0
  fi
  for id in $CONTRACT_TCC_BUNDLE_IDS; do
    ok=0
    refused=0
    for service in $CONTRACT_TCC_SERVICES; do
      if [[ "$mode" == dry ]]; then
        contract_say "[dry-run] would run: tccutil reset $service $id"
      elif tccutil reset "$service" "$id" </dev/null >/dev/null 2>&1; then
        ok=$((ok + 1))
      else
        refused=$((refused + 1))
      fi
    done
    if [[ "$mode" != dry ]]; then
      contract_say "privacy rows for $id: $ok reset, $refused refused"
      if [[ "$refused" -gt 0 ]]; then contract_say "  (macOS refuses an app id it does not know, for example once the app is gone; rows left behind come back if the same app is installed again)"; fi
    fi
  done
}

contract_bundled_tmux() {
  local tmux_bin bundle arch
  arch="$(uname -m)"
  bundle="$(contract_find_bundle)"
  tmux_bin="$bundle/Contents/Resources/payload/payload-$arch/bin/tmux"
  if [[ -n "$bundle" && -x "$tmux_bin" ]]; then printf '%s\n' "$tmux_bin"; fi
  return 0
}

contract_socket_is_ours() {
  case " $CONTRACT_TMUX_SOCKETS " in
    *" $1 "*) return 0 ;;
  esac
  return 1
}

contract_stop_tmux() {
  local mode="$1" socket="$2" given="${3:-}" candidate tried=0 out rc ended=0
  local -a candidates
  if ! contract_socket_is_ours "$socket"; then
    contract_say "tmux: socket '$socket' is not one of ours ($CONTRACT_TMUX_SOCKETS), left alone"
    return 0
  fi
  if [[ -n "$given" ]]; then
    candidates=("$given")
  else
    candidates=("$(contract_bundled_tmux)" "$(command -v tmux || true)")
  fi
  for candidate in "${candidates[@]}"; do
    if [[ -z "$candidate" ]]; then continue; fi
    tried=1
    if [[ "$mode" == dry ]]; then
      contract_say "[dry-run] would run: $candidate -L $socket kill-server"
      continue
    fi
    "$candidate" -L "$socket" kill-server </dev/null >/dev/null 2>&1 || true
    rc=0
    out="$("$candidate" -L "$socket" list-sessions </dev/null 2>&1)" || rc=$?
    if [[ "$rc" == 0 ]]; then
      contract_say "tmux: socket $socket still has sessions after $candidate kill-server"
    elif printf '%s\n' "$out" | grep -qi 'version mismatch'; then
      contract_say "tmux: $candidate could not talk to the server on socket $socket (tmux version mismatch)"
    else
      contract_say "tmux: socket $socket has no server left"
      ended=1
      break
    fi
  done
  if [[ "$tried" == 0 ]]; then contract_say "tmux: no tmux found, socket $socket left alone"; fi
  if [[ "$tried" == 1 && "$ended" == 0 && "$mode" != dry ]]; then contract_say "tmux: the sessions on socket $socket may still be running"; fi
  return 0
}

CONTRACT_SYSTEM=1
CONTRACT_HOME="$HOME"
CONTRACT_LAUNCHCTL=launchctl

say() {
  printf '%s\n' "$*"
}

fail() {
  printf 'carnivore: %s\n' "$1" >&2
  exit "${2:-1}"
}

have_tty() {
  { : <"$TTY_DEV"; } 2>/dev/null
}

usage() {
  say "usage: bash -c \"\$(curl -fsSL https://carnivore.ai/uninstall.sh)\" _ [--yes] [--stop-tmux] [--dry-run]"
  say "  --yes        do not ask before removing"
  say "  --stop-tmux  also end the carnivore terminal sessions (work running in them stops); without it they keep running"
  say "  --dry-run    print what would be removed and change nothing"
}

parse_args() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --yes) ASSUME_YES=1 ;;
      --dry-run) DRY_RUN=1 ;;
      --stop-tmux) STOP_TMUX=1 ;;
      --tmux-bin)
        [[ "$#" -ge 2 ]] || fail "--tmux-bin needs a path" 2
        TMUX_BIN_GIVEN="$2"
        shift
        ;;
      --help | -h) usage; exit 0 ;;
      *) usage >&2; fail "unknown option $1" 2 ;;
    esac
    shift
  done
}

preflight() {
  [[ "$(uname -s)" == Darwin ]] || fail "carnivore runs on macos only"
  [[ "$(id -u)" != 0 ]] || fail "do not run this as root or with sudo. run it as the user who installed carnivore."
  [[ "${HOME:-}" == /?* && "$HOME" != "/" && "$HOME" != "//" ]] || fail "HOME is not set to a real folder"
  case "$(basename "$(printf %s "${TMUX:-}" | cut -d, -f1)")" in
    cloude | carnivore) fail "this is a carnivore terminal, and removing carnivore ends it. run this from Terminal.app instead." 2 ;;
  esac
}

build_paths() {
  local lib="$HOME/Library"
  PATHS=(
    "$APP"
    "$lib/Application Support/Carnivore"
    "$lib/Application Support/Carnivore Menubar"
    "$lib/Application Support/CloudeCode"
    "$lib/Application Support/cloude-code-menubar"
    "$lib/LaunchAgents/ai.carnivore.menubar.plist"
    "$lib/LaunchAgents/com.cloudecode.menubar.plist"
    "$lib/Preferences/ai.carnivore.menubar.plist"
    "$lib/Preferences/com.cloudecode.menubar.plist"
    "$lib/Caches/ai.carnivore.menubar"
    "$lib/Caches/ai.carnivore.menubar.ShipIt"
    "$lib/Caches/cloude-code-menubar-updater"
    "$lib/Caches/Carnivore"
    "$lib/HTTPStorages/ai.carnivore.menubar"
    "$lib/Saved Application State/ai.carnivore.menubar.savedState"
    "$lib/Logs/Carnivore"
    "$lib/Logs/cloude-code"
    "/Applications/.Carnivore-staging.app"
    "/Applications/.Carnivore-previous.app"
  )
}

find_cplug_services() {
  local line
  CPLUG_SERVICES=()
  while IFS= read -r line; do
    [[ "$line" =~ ^carnivore-cplug-[A-Za-z0-9._-]+$ ]] && CPLUG_SERVICES+=("$line")
  done < <(security dump-keychain 2>/dev/null </dev/null |
    sed -n 's/.*"svce"<blob>="\(carnivore-cplug-[^"]*\)".*/\1/p' | sort -u)
  return 0
}

anything_left() {
  local p s
  for p in "${PATHS[@]}"; do
    [[ -e "$p" || -L "$p" ]] && return 0
  done
  for s in $KEYCHAIN_SERVICES ${CPLUG_SERVICES[@]+"${CPLUG_SERVICES[@]}"}; do
    security find-generic-password -s "$s" </dev/null >/dev/null 2>&1 && return 0
  done
  [[ -z "$(contract_launchd_left)" ]] || return 0
  return 1
}

show_plan() {
  local p s
  say "this removes carnivore from this computer:"
  say ""
  say "  stops: the carnivore app, its login service and login items (${CONTRACT_SERVICE_LABEL} ${LOGIN_LABELS}) and its server"
  say "  resets: carnivore's privacy rows (tccutil, bundle ids ${CONTRACT_TCC_BUNDLE_IDS})"
  if [[ "$STOP_TMUX" == 1 ]]; then
    say "  ends:  every carnivore terminal session on this computer (tmux sockets: ${CONTRACT_TMUX_SOCKETS}). work running inside them stops."
  else
    say "  keeps: your carnivore terminal sessions running (add --stop-tmux to end them)"
  fi
  say "  deletes:"
  for p in "${PATHS[@]}"; do
    say "    $p"
  done
  say "  deletes keychain items:"
  for s in $KEYCHAIN_SERVICES ${CPLUG_SERVICES[@]+"${CPLUG_SERVICES[@]}"}; do
    say "    $s"
  done
  say ""
  say "it keeps ~/carnivore-projects, ~/.claude, ~/.carnivore, your Claude Code and Codex logins and any Claude Code keychain items a pack relay wrote."
  say ""
}

confirm() {
  [[ "$ASSUME_YES" == 1 ]] && return 0
  have_tty || fail "this needs a terminal to ask you. run it from a Terminal window, or add --yes." 2
  local answer=""
  printf 'type yes to remove carnivore: ' >"$TTY_DEV"
  IFS= read -r answer <"$TTY_DEV" || answer=""
  [[ "$answer" == yes ]] || fail "nothing was removed" 3
}

safe_remove() {
  local p="$1"
  case "$p" in
    "$HOME"/Library/?*) ;;
    "$APP" | /Applications/.Carnivore-staging.app | /Applications/.Carnivore-previous.app) ;;
    *) return 1 ;;
  esac
  rm -rf "${p:?}"
}

delete_keychain_service() {
  local service="$1" n=0
  while [[ "$n" -lt "$KEYCHAIN_BOUND" ]]; do
    security delete-generic-password -s "$service" </dev/null >/dev/null 2>&1 || break
    n=$((n + 1))
  done
}

server_pids() {
  local p cwd
  for p in $(pgrep -f 'src\.main' </dev/null 2>/dev/null); do
    cwd="$(lsof -a -p "$p" -d cwd -Fn </dev/null 2>/dev/null | sed -n 's/^n//p')"
    [[ "$cwd" == "$HOME/Library/Application Support/Carnivore Menubar/server" ]] && printf '%s\n' "$p"
  done
  return 0
}

stop_app() {
  local i=0
  osascript -e 'quit app "Carnivore"' </dev/null >/dev/null 2>&1 || true
  while [[ "$i" -lt 15 ]]; do
    pgrep -f "$APP_PATTERN" </dev/null >/dev/null 2>&1 || return 0
    sleep 1
    i=$((i + 1))
  done
  pkill -f "$APP_PATTERN" </dev/null >/dev/null 2>&1 || true
  sleep 2
  pkill -9 -f "$APP_PATTERN" </dev/null >/dev/null 2>&1 || true
}

stop_server() {
  local p
  for p in $(server_pids); do kill "$p" >/dev/null 2>&1 || true; done
  sleep 2
  for p in $(server_pids); do kill -9 "$p" >/dev/null 2>&1 || true; done
}

stop_everything() {
  local label
  say "stopping carnivore"
  contract_unregister_login_service run
  contract_unregister_agents run
  stop_app
  for label in $LOGIN_LABELS; do
    launchctl bootout "gui/$(id -u)/$label" </dev/null >/dev/null 2>&1 || true
  done
  stop_server
}

ask_stop_tmux() {
  [[ "$STOP_TMUX" == 1 || "$ASSUME_YES" == 1 ]] && return 0
  have_tty || return 0
  local answer=""
  printf 'also end the carnivore terminal sessions? work running in them stops. type yes to end them, anything else keeps them: ' >"$TTY_DEV"
  IFS= read -r answer <"$TTY_DEV" || answer=""
  [[ "$answer" == yes ]] && STOP_TMUX=1
  return 0
}

stop_tmux() {
  local sock tmux_hint
  if [[ "$STOP_TMUX" != 1 ]]; then
    tmux_hint="$(contract_bundled_tmux)"
    say "your carnivore terminal sessions keep running (tmux sockets: ${CONTRACT_TMUX_SOCKETS}); end them any time with: '${tmux_hint:-tmux}' -L cloude kill-server"
    return 0
  fi
  for sock in $CONTRACT_TMUX_SOCKETS; do
    contract_stop_tmux "$1" "$sock" "$TMUX_BIN_GIVEN"
  done
}

finish_login() {
  local left
  contract_record_background_items
  left="$(contract_launchd_left)"
  [[ -z "$left" ]] || fail "a carnivore login job is still loaded: $(printf '%s' "$left" | tr '\n' ' '). run: launchctl bootout gui/$(id -u)/<label>" 4
}

remove_everything() {
  local p s failed=0
  say "removing files"
  for p in "${PATHS[@]}"; do
    safe_remove "$p" || say "could not remove $p"
    if [[ -e "$p" || -L "$p" ]]; then failed=1; fi
  done
  say "removing keychain items"
  for s in $KEYCHAIN_SERVICES ${CPLUG_SERVICES[@]+"${CPLUG_SERVICES[@]}"}; do
    delete_keychain_service "$s"
  done
  return "$failed"
}

finish_notes() {
  say ""
  if [[ "${1:-}" == removed ]]; then say "carnivore is removed from this computer."; fi
  say "if this computer was in a pack: on your main computer, open carnivore, go to pack, computers, and remove this computer from the list."
  say "to install carnivore again: bash -c \"\$(curl -fsSL https://carnivore.ai/install.sh)\" _ --new"
}

main() {
  set -euo pipefail
  parse_args "$@"
  preflight
  build_paths
  find_cplug_services
  if ! anything_left; then
    say "nothing to remove. carnivore is not installed on this computer."
    finish_notes
    return 0
  fi
  show_plan
  if [[ "$DRY_RUN" == 1 ]]; then
    contract_unregister_login_service dry
    contract_unregister_agents dry
    contract_reset_tcc dry
    stop_tmux dry
    say "dry run: nothing was changed."
    return 0
  fi
  confirm
  ask_stop_tmux
  stop_everything
  contract_reset_tcc run
  stop_tmux run
  if ! remove_everything; then
    fail "some files could not be removed (see above). close anything using them and run this again." 4
  fi
  finish_login
  finish_notes removed
}

main "$@"
