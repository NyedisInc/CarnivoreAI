---
title: Uninstall carnivore
slug: uninstall
parent: null
order: 90
features: [carnivore-public-site]
sources:
  - hosted/site/uninstall.sh

# Uninstall carnivore

```
bash -c "$(curl -fsSL https://carnivore.ai/uninstall.sh)"
```

It lists everything it will remove and asks you to type yes before it touches anything. Add `_ --dry-run` after the quoted command to only print the list and change nothing, or `_ --yes` to skip the question, like this: `bash -c "$(curl -fsSL https://carnivore.ai/uninstall.sh)" _ --dry-run`. Run it from Terminal.app, not from a carnivore terminal, because it ends those. The script is short and is printed in full at the bottom of this page, so you can read it before you run it.

## What it removes

- **The app, its login service and its processes.** It quits Carnivore, unregisters the login service the app may have registered (macOS Background Items), stops its login items and its server, and resets the privacy rows (tccutil) carnivore was granted. macOS keeps its own Background Items record; `sudo sfltool dumpbtm` shows what is left.
- **Your carnivore terminal sessions: only when you ask.** By default they keep running (the `cloude` and `carnivore` tmux servers are left alone). Add `_ --stop-tmux` after the quoted command to end them, or type yes when it asks on a terminal; whatever is running inside a carnivore terminal then ends, so save your work first.
- **The app folder.** `/Applications/Carnivore.app`.
- **Settings, state and caches.** The folders `Carnivore`, `Carnivore Menubar`, `CloudeCode` and `cloude-code-menubar` in `~/Library/Application Support`, the login item files in `~/Library/LaunchAgents`, the preferences files, caches, saved window state and update leftovers for `ai.carnivore.menubar`, the old logs in `~/Library/Logs`, and the hidden staging copies of the app in `/Applications`.
- **Keychain items carnivore created.** Its pack and relay keys, catalog key, saved AI provider, notification and messaging keys, and one item per plugin secret.

Nothing outside that fixed list is ever deleted.

## What it keeps

- `~/carnivore-projects`, which holds your own code.
- `~/.claude`, and your Claude Code and Codex logins.
- `~/.carnivore`, which holds full Claude Code profiles (logins, history, memory). The script never touches it.
- The `Claude Code-credentials-*` Keychain items a pack relay may have written.

## Install again

```
bash -c "$(curl -fsSL https://carnivore.ai/install.sh)" _ --new
```

## The script

The same file is served at [uninstall.sh](https://carnivore.ai/uninstall.sh). Its sha256 is `ad890c81d141e86a373a2058ea00ab3ec95b781079046b81c0197fb8c6e1c2d0`.

```
#!/usr/bin/env bash
# carnivore uninstaller, served at https://carnivore.ai/uninstall.sh
#
#   bash -c "$(curl -fsSL https://carnivore.ai/uninstall.sh)"
#
# removes carnivore from this computer: quits the app, unregisters its login service
# and login items, stops its server, deletes the app, its settings and state, the
# keychain items it created, and resets the privacy rows (tccutil) it was granted.
# it keeps ~/carnivore-projects, every project folder, ~/.claude, ~/.carnivore and the
# Claude Code and Codex logins, and the Claude Code keychain items a pack relay may
# have written. the carnivore tmux sessions keep running unless you ask for them to stop.
# flags: --yes (skip the question), --stop-tmux (also end the carnivore tmux sessions;
# without it an interactive run asks and --yes leaves them running), --dry-run (print
# what would go, change nothing), --help.
# every path below is fixed; nothing outside this list is ever deleted.
# the whole body lives in main(), called on the last line, so a truncated
# download runs nothing.

APP="/Applications/Carnivore.app"
LOGIN_LABELS="ai.carnivore.menubar com.cloudecode.menubar ai.carnivore.install-launch"
# the app's own programs only (the shell and its helpers), NOT Contents/Resources/payload: the bundled tmux server that holds
# your terminal sessions runs from there and must survive unless you ask for it to stop.
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

# --- uninstall contract: begin ---
# The same text sits in hosted/site/uninstall.sh and nuke.sh, and tests/python/release/test_uninstall_contract.py fails when
# the two copies differ. Docs: docs/desktop-app.md, "Uninstall and nuke". A script that needs a different value assigns it
# AFTER this block; it never edits the block. MODE below is run or dry.
CONTRACT_APP="/Applications/Carnivore.app"
CONTRACT_SERVICE_LABEL="ai.carnivore.menubar.engine"
CONTRACT_AGENT_LABELS="ai.carnivore.menubar com.cloudecode.menubar"
CONTRACT_TCC_BUNDLE_IDS="ai.carnivore.menubar com.cloudecode.menubar"
CONTRACT_TCC_SERVICES="AppleEvents SystemPolicyAllFiles SystemPolicyAppData SystemPolicyDocumentsFolder SystemPolicyDesktopFolder SystemPolicyDownloadsFolder SystemPolicyRemovableVolumes SystemPolicyNetworkVolumes"
CONTRACT_TMUX_SOCKETS="cloude carnivore"
# the first release whose app understands --unregister-login-service; an older app would start as a full GUI app instead.
CONTRACT_MIN_APP_VERSION="1.16.4"

# contract_say MESSAGE: print one line of the contract's progress.
contract_say() {
  printf '%s\n' "$*"
}

# contract_find_bundle: print the folder of the installed Carnivore app wherever it is (the login job's own program, the
# Applications folder, ~/Applications, the Trash), or nothing.
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

# contract_app_bin: print the app's executable when the app is installed, else nothing.
contract_app_bin() {
  local bundle
  bundle="$(contract_find_bundle)"
  if [[ -n "$bundle" ]]; then printf '%s\n' "$bundle/Contents/MacOS/Carnivore"; fi
  return 0
}

# contract_app_version BUNDLE: print the app's CFBundleShortVersionString, or nothing when it cannot be read.
contract_app_version() {
  sed -n '/<key>CFBundleShortVersionString<\/key>/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "$1/Contents/Info.plist" 2>/dev/null | head -n 1
  return 0
}

# contract_version_at_least ACTUAL MINIMUM: succeed when the dotted version ACTUAL is MINIMUM or newer; fails on a non-number.
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

# contract_service_registered: succeed when an engine login job is loaded now or the install is set to the launchd-agent host.
contract_service_registered() {
  local home="${CONTRACT_HOME:-$HOME}" launchctl_bin="${CONTRACT_LAUNCHCTL:-launchctl}"
  if "$launchctl_bin" print "gui/$(id -u)/$CONTRACT_SERVICE_LABEL" </dev/null >/dev/null 2>&1; then return 0; fi
  grep -q 'launchd-agent' "$home/Library/Application Support/Carnivore Menubar/engine-host.json" 2>/dev/null
}

# contract_run_bounded SECONDS COMMAND...: run COMMAND, end it when it outlives SECONDS; its status, 124 on a timeout.
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

# contract_unregister_login_service MODE: have the installed app unregister the engine login service (only when an engine
# login job exists and the app is new enough to know the flag), then boot the job out with launchctl.
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

# contract_unregister_agents MODE: boot out both menubar LaunchAgent labels and remove their plists. Booting out the label that
# started the running app ends that app and its process group, so nuke.sh calls this last.
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

# contract_launchd_left: print every launchd job of ours that is still loaded for this user (none when the list is empty).
contract_launchd_left() {
  local label launchctl_bin="${CONTRACT_LAUNCHCTL:-launchctl}"
  if [[ "${CONTRACT_SYSTEM:-1}" != 1 ]]; then return 0; fi
  for label in "$CONTRACT_SERVICE_LABEL" $CONTRACT_AGENT_LABELS; do
    if "$launchctl_bin" print "gui/$(id -u)/$label" </dev/null >/dev/null 2>&1; then printf '%s\n' "$label"; fi
  done
  return 0
}

# contract_record_background_items: say what Background Items still lists for us. macOS lets only root read the list
# (sfltool dumpbtm), so a regular user gets the sudo command to run; root runs it bounded.
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

# contract_reset_tcc MODE: reset OUR privacy rows only (each service the app holds, for each of our two bundle ids).
# Never "All", never another bundle id. tccutil answers "No such bundle identifier" once the app is deleted (it works while
# the app is in /Applications or the Trash), so callers run this BEFORE they delete the app.
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

# contract_bundled_tmux: print the tmux the app bundle ships for this computer's architecture, or nothing.
contract_bundled_tmux() {
  local tmux_bin bundle arch
  arch="$(uname -m)"
  bundle="$(contract_find_bundle)"
  tmux_bin="$bundle/Contents/Resources/payload/payload-$arch/bin/tmux"
  if [[ -n "$bundle" && -x "$tmux_bin" ]]; then printf '%s\n' "$tmux_bin"; fi
  return 0
}

# contract_socket_is_ours SOCKET: succeed only for a tmux socket name carnivore itself uses (never "default", never a name
# read from a config file that was edited).
contract_socket_is_ours() {
  case " $CONTRACT_TMUX_SOCKETS " in
    *" $1 "*) return 0 ;;
  esac
  return 1
}

# contract_stop_tmux MODE SOCKET [TMUX_BIN]: end the tmux server on ONE named socket of ours (never the default socket,
# never your own tmux server) and say whether it ended. TMUX_BIN when given, else the bundled tmux first; a tmux on PATH
# is then tried on the same socket only because a server started by another tmux version refuses the bundled one.
# Callers run this only when asked, and before they delete the app the bundled tmux lives in.
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
# --- uninstall contract: end ---

# the block reads these three; they are set here and never taken from the environment.
CONTRACT_SYSTEM=1
CONTRACT_HOME="$HOME"
CONTRACT_LAUNCHCTL=launchctl

# say MESSAGE: print one progress line.
say() {
  printf '%s\n' "$*"
}

# fail MESSAGE [STATUS]: print MESSAGE to stderr and stop with STATUS (default 1).
fail() {
  printf 'carnivore: %s\n' "$1" >&2
  exit "${2:-1}"
}

# have_tty: succeed when the person's terminal can be read.
have_tty() {
  { : <"$TTY_DEV"; } 2>/dev/null
}

# usage: print the flags.
usage() {
  say "usage: bash -c \"\$(curl -fsSL https://carnivore.ai/uninstall.sh)\" _ [--yes] [--stop-tmux] [--dry-run]"
  say "  --yes        do not ask before removing"
  say "  --stop-tmux  also end the carnivore terminal sessions (work running in them stops); without it they keep running"
  say "  --dry-run    print what would be removed and change nothing"
}

# parse_args ARGS...: read the flags.
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

# preflight: macos only, not root, a real home, and an app path that is the carnivore app.
preflight() {
  [[ "$(uname -s)" == Darwin ]] || fail "carnivore runs on macos only"
  [[ "$(id -u)" != 0 ]] || fail "do not run this as root or with sudo. run it as the user who installed carnivore."
  [[ "${HOME:-}" == /?* && "$HOME" != "/" && "$HOME" != "//" ]] || fail "HOME is not set to a real folder"
  # stopping the tmux servers below would end this script when it runs inside a carnivore terminal.
  case "$(basename "$(printf %s "${TMUX:-}" | cut -d, -f1)")" in
    cloude | carnivore) fail "this is a carnivore terminal, and removing carnivore ends it. run this from Terminal.app instead." 2 ;;
  esac
}

# build_paths: the fixed list of files and folders this script may delete.
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

# find_cplug_services: list per-plugin keychain service names. dump-keychain without -d
# prints attributes only, never secret data; only names of the exact shape are kept.
find_cplug_services() {
  local line
  CPLUG_SERVICES=()
  while IFS= read -r line; do
    [[ "$line" =~ ^carnivore-cplug-[A-Za-z0-9._-]+$ ]] && CPLUG_SERVICES+=("$line")
  done < <(security dump-keychain 2>/dev/null </dev/null |
    sed -n 's/.*"svce"<blob>="\(carnivore-cplug-[^"]*\)".*/\1/p' | sort -u)
  return 0
}

# anything_left: succeed when any listed path, keychain item or loaded login job of ours still exists.
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

# show_plan: print everything this run will do.
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

# confirm: ask on the terminal (the script is usually piped); --yes skips it.
confirm() {
  [[ "$ASSUME_YES" == 1 ]] && return 0
  have_tty || fail "this needs a terminal to ask you. run it from a Terminal window, or add --yes." 2
  local answer=""
  printf 'type yes to remove carnivore: ' >"$TTY_DEV"
  IFS= read -r answer <"$TTY_DEV" || answer=""
  [[ "$answer" == yes ]] || fail "nothing was removed" 3
}

# safe_remove PATH: delete one listed path; refuses anything not under ~/Library or the app folder.
safe_remove() {
  local p="$1"
  case "$p" in
    "$HOME"/Library/?*) ;;
    "$APP" | /Applications/.Carnivore-staging.app | /Applications/.Carnivore-previous.app) ;;
    *) return 1 ;;
  esac
  rm -rf "${p:?}"
}

# delete_keychain_service SERVICE: delete every generic password item of one service, bounded.
delete_keychain_service() {
  local service="$1" n=0
  while [[ "$n" -lt "$KEYCHAIN_BOUND" ]]; do
    security delete-generic-password -s "$service" </dev/null >/dev/null 2>&1 || break
    n=$((n + 1))
  done
}

# server_pids: print the pid of every carnivore server (python -m src.main whose cwd is the
# app's server folder). A bystander claude or mcp bridge never matches.
server_pids() {
  local p cwd
  for p in $(pgrep -f 'src\.main' </dev/null 2>/dev/null); do
    cwd="$(lsof -a -p "$p" -d cwd -Fn </dev/null 2>/dev/null | sed -n 's/^n//p')"
    [[ "$cwd" == "$HOME/Library/Application Support/Carnivore Menubar/server" ]] && printf '%s\n' "$p"
  done
  return 0
}

# stop_app: quit the app, wait up to about 15 s, then end whatever is left of it.
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
  # a modal dialog (the first quit notice) can hold a quit and a terminate: end what is still there.
  pkill -9 -f "$APP_PATTERN" </dev/null >/dev/null 2>&1 || true
}

# stop_server: end the carnivore server only, then force anything that is still up.
stop_server() {
  local p
  for p in $(server_pids); do kill "$p" >/dev/null 2>&1 || true; done
  sleep 2
  for p in $(server_pids); do kill -9 "$p" >/dev/null 2>&1 || true; done
}

# stop_everything: unregister the login service, quit the app, boot out the login items, stop the server.
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

# ask_stop_tmux: on a terminal without --yes, ask whether to end the carnivore terminal sessions; the default is no.
ask_stop_tmux() {
  [[ "$STOP_TMUX" == 1 || "$ASSUME_YES" == 1 ]] && return 0
  have_tty || return 0
  local answer=""
  printf 'also end the carnivore terminal sessions? work running in them stops. type yes to end them, anything else keeps them: ' >"$TTY_DEV"
  IFS= read -r answer <"$TTY_DEV" || answer=""
  [[ "$answer" == yes ]] && STOP_TMUX=1
  return 0
}

# stop_tmux MODE: when asked for, end the carnivore terminal sessions with the bundled tmux (it runs before the app is deleted).
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

# finish_login: record Background Items, and fail when a login job of ours is still loaded.
finish_login() {
  local left
  contract_record_background_items
  left="$(contract_launchd_left)"
  [[ -z "$left" ]] || fail "a carnivore login job is still loaded: $(printf '%s' "$left" | tr '\n' ' '). run: launchctl bootout gui/$(id -u)/<label>" 4
}

# remove_everything: delete the listed paths and keychain items; returns 1 when a path is still there.
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

# finish_notes: what is left for the person to do.
finish_notes() {
  say ""
  if [[ "${1:-}" == removed ]]; then say "carnivore is removed from this computer."; fi
  say "if this computer was in a pack: on your main computer, open carnivore, go to pack, computers, and remove this computer from the list."
  say "to install carnivore again: bash -c \"\$(curl -fsSL https://carnivore.ai/install.sh)\" _ --new"
}

# main: run every step in order.
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
  # the terminal sessions end while the app's own tmux is still on disk, and before anything below can stop the script.
  stop_tmux run
  if ! remove_everything; then
    fail "some files could not be removed (see above). close anything using them and run this again." 4
  fi
  finish_login
  finish_notes removed
}

main "$@"
```
