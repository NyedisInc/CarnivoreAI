#!/usr/bin/env bash

APP="/Applications/Carnivore.app"
LOGIN_LABELS="ai.carnivore.menubar com.cloudecode.menubar ai.carnivore.install-launch"
TMUX_SOCKETS="cloude carnivore"
APP_PATTERN="/Applications/Carnivore.app/Contents/"
KEYCHAIN_SERVICES="ai.carnivore.federation.key ai.carnivore.relay.device-key ai.carnivore.relay.legacy-publish-token ai.carnivore.catalog.guest-key carnivore-byoai carnivore-notifications carnivore-messaging carnivore-native-push carnivore-summary-api carnivore-summary-local"
KEYCHAIN_BOUND=100
ASSUME_YES=0
DRY_RUN=0
PATHS=()
CPLUG_SERVICES=()
TTY_DEV=/dev/tty

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
  say "usage: bash -c \"\$(curl -fsSL https://carnivore.ai/uninstall.sh)\" _ [--yes] [--dry-run]"
  say "  --yes      do not ask before removing"
  say "  --dry-run  print what would be removed and change nothing"
}

parse_args() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      --yes) ASSUME_YES=1 ;;
      --dry-run) DRY_RUN=1 ;;
      --help | -h) usage; exit 0 ;;
      *) usage >&2; fail "unknown option $arg" 2 ;;
    esac
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
  return 1
}

show_plan() {
  local p s
  say "this removes carnivore from this computer:"
  say ""
  say "  stops: the carnivore app, its login items (${LOGIN_LABELS}) and its server"
  say "  ends:  every carnivore terminal session on this computer (tmux sockets: ${TMUX_SOCKETS})."
  say "         work running inside them stops."
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
  stop_app
  for label in $LOGIN_LABELS; do
    launchctl bootout "gui/$(id -u)/$label" </dev/null >/dev/null 2>&1 || true
  done
  stop_server
}

stop_tmux() {
  local sock
  for sock in $TMUX_SOCKETS; do
    tmux -L "$sock" kill-server </dev/null >/dev/null 2>&1 || true
  done
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
    say "dry run: nothing was changed."
    return 0
  fi
  confirm
  stop_everything
  if ! remove_everything; then
    fail "some files could not be removed (see above). close anything using them and run this again." 4
  fi
  stop_tmux
  finish_notes removed
}

main "$@"
