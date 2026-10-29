#!/bin/bash


set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"
source "${SCRIPT_DIR}/scripts/resolve-port.sh"
source "${SCRIPT_DIR}/scripts/upgrade_lib/upgrade_rollback_common.sh"

echo "Cloude Code - Nuke it from Orbit!"
echo "========================================"
echo ""

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SKIP_CONFIRM=false
DRY_RUN="${CLOUDE_NUKE_DRY_RUN:-false}"
for arg in "$@"; do
    case "$arg" in
        --skip-confirm) SKIP_CONFIRM=true ;;
        --dry-run)      DRY_RUN=true ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: nuke.sh [--skip-confirm] [--dry-run]" >&2
            exit 2
            ;;
    esac
done
[ "$SKIP_CONFIRM" = "true" ] && echo "Running in non-interactive mode (confirmation already provided)"
[ "$DRY_RUN" = "true" ] && echo -e "${YELLOW}DRY RUN - nothing will be deleted.${NC}"


NUKE_HOME="${CLOUDE_NUKE_HOME:-$HOME}"
NUKE_TMP="${CLOUDE_NUKE_TMP_DIR:-/tmp}"
LAUNCHCTL_BIN="${CLOUDE_NUKE_LAUNCHCTL:-launchctl}"
PGREP_PATTERN="${CLOUDE_NUKE_PGREP_PATTERN-Cloude Code|Carnivore}"
TMUX_BIN="${CLOUDE_NUKE_TMUX_BIN:-tmux}"
KILL_TMUX="${CLOUDE_NUKE_KILL_TMUX:-false}"

cd "$PROJECT_ROOT"

if [ -f "${PROJECT_ROOT}/.env" ]; then
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
fi


if ! STATE_DIR="$(resolve_state_dir "$PROJECT_ROOT" 2>/dev/null)" || [ -z "$STATE_DIR" ]; then
    echo -e "${RED}FATAL${NC}: could not resolve the Cloude Code state directory." >&2
    echo "  resolve_state_dir() failed. It needs either ${PROJECT_ROOT}/venv/bin/python3" >&2
    echo "  or a python3 on PATH. Refusing to continue: the state directory holds" >&2
    echo "  cloude.db and refresh_tokens.db, and a reset that skips them is not a" >&2
    echo "  reset. Fix the interpreter, or set CLOUDE_STATE_DIR explicitly, and" >&2
    echo "  re-run. NOTHING has been deleted." >&2
    exit 1
fi
case "$STATE_DIR" in
    /*) ;;
    *)
        echo -e "${RED}FATAL${NC}: resolved state directory is not an absolute path: '${STATE_DIR}'. Refusing to continue. NOTHING has been deleted." >&2
        exit 1
        ;;
esac
for forbidden in "/" "$HOME" "$NUKE_HOME" "/Users" "/Library" "$HOME/Library" "$HOME/Library/Application Support"; do
    if [ "${STATE_DIR%/}" = "${forbidden%/}" ]; then
        echo -e "${RED}FATAL${NC}: resolved state directory '${STATE_DIR}' is a protected path. Refusing to continue. NOTHING has been deleted." >&2
        exit 1
    fi
done
echo -e "${BLUE}i${NC} State directory resolved to: ${STATE_DIR}"

echo ""
if [ "$SKIP_CONFIRM" = "false" ] && [ "$DRY_RUN" = "false" ]; then
    echo -e "${RED}WARNING${NC}"
    echo ""
    echo "This will completely remove ALL Cloude Code configuration and setup:"
    echo ""
    echo "  x All local configuration files (.env, config.json, etc.)"
    echo "  x Python virtual environment"
    echo "  x The state directory and everything in it, INCLUDING the"
    echo "    session database and your stored refresh tokens:"
    echo "      ${STATE_DIR}"
    echo "  x All logs and temporary files"
    echo "  x macOS app settings and LaunchAgent"
    echo ""
    echo -e "${YELLOW}You will need to run setup.sh again to use Cloude Code.${NC}"
    echo ""
    read -p "Are you ABSOLUTELY SURE you want to continue? (type 'NUKE' to confirm): " CONFIRM

    if [ "$CONFIRM" != "NUKE" ]; then
        echo ""
        echo "Aborted. No changes made."
        exit 0
    fi
fi

echo ""
echo "========================================"
echo "Starting cleanup process..."
echo "========================================"
echo ""

CLEANUP_LOG=()

log_cleanup() {
    local message=$1
    CLEANUP_LOG+=("$message")
    echo -e "${GREEN}v${NC} $message"
}

log_skip() {
    local message=$1
    echo -e "${BLUE}o${NC} $message (not found, skipping)"
}

log_unknown_target() {
    echo -e "${YELLOW}?${NC} CANNOT DETERMINE / NOT ACTIONED: $1"
}

nuke_path() {
    local target="$1" label="$2"
    if [ -e "$target" ] || [ -L "$target" ]; then
        if [ "$DRY_RUN" = "true" ]; then
            log_cleanup "[dry-run] would remove: ${label}"
        else
            rm -rf "$target"
            log_cleanup "Removed: ${label}"
        fi
    else
        log_skip "$label"
    fi
}

echo "Stopping running processes..."
echo "--------------------------------------"

if PORT="$(resolve_port "${PROJECT_ROOT}")"; then
    SERVER_PID=$(lsof -ti:"${PORT}" 2>/dev/null || echo "")
    if [ -n "$SERVER_PID" ]; then
        if [ "$DRY_RUN" = "true" ]; then
            log_cleanup "[dry-run] would stop server on port ${PORT} (PID: $SERVER_PID)"
        else
            kill -9 $SERVER_PID 2>/dev/null || true
            log_cleanup "Stopped server process on port ${PORT} (PID: $SERVER_PID)"
        fi
    else
        log_skip "Server process not running on port ${PORT}"
    fi
else
    log_unknown_target "port could not be determined (see reason above); the port-based server kill was skipped. If the server is still running, stop it manually."
fi

if [ -z "$PGREP_PATTERN" ]; then
    log_unknown_target "process kill disabled (CLOUDE_NUKE_PGREP_PATTERN is empty). Any running menubar app was NOT stopped."
else
    MENUBAR_PIDS=$(pgrep -f "$PGREP_PATTERN" || echo "")
    if [ -n "$MENUBAR_PIDS" ]; then
        if [ "$DRY_RUN" = "true" ]; then
            log_cleanup "[dry-run] would kill processes matching '${PGREP_PATTERN}': $(echo $MENUBAR_PIDS | tr '\n' ' ')"
        else
            echo "$MENUBAR_PIDS" | xargs kill -9 2>/dev/null || true
            log_cleanup "Stopped macOS menubar app"
        fi
    else
        log_skip "macOS menubar app not running"
    fi
fi

echo ""

echo "tmux sessions..."
echo "--------------------------------------"

TMUX_SOCKET="${CLOUDE_NUKE_TMUX_SOCKET:-}"
if [ -z "$TMUX_SOCKET" ] && [ -f "${PROJECT_ROOT}/config.json" ]; then
    TMUX_SOCKET="$("$(resolve_python "$PROJECT_ROOT")" -c '
import json, sys
try:
    with open(sys.argv[1]) as fh:
        print(json.load(fh).get("session", {}).get("tmux_socket_name", "") or "")
except Exception:
    print("")
' "${PROJECT_ROOT}/config.json" 2>/dev/null || echo "")"
fi
TMUX_SOCKET="${TMUX_SOCKET:-cloude}"

if [ "$KILL_TMUX" != "true" ]; then
    log_unknown_target "tmux socket '${TMUX_SOCKET}' was NOT killed. A tmux socket is shared by every checkout run as this user, so sessions on it cannot be attributed to this install. Kill it yourself with: ${TMUX_BIN} -L ${TMUX_SOCKET} kill-server  (or re-run with CLOUDE_NUKE_KILL_TMUX=true)."
elif ! command -v "$TMUX_BIN" >/dev/null 2>&1 && [ ! -x "$TMUX_BIN" ]; then
    log_unknown_target "CLOUDE_NUKE_KILL_TMUX=true but tmux ('${TMUX_BIN}') was not found. Socket '${TMUX_SOCKET}' left alone."
elif [ "$DRY_RUN" = "true" ]; then
    log_cleanup "[dry-run] would run: ${TMUX_BIN} -L ${TMUX_SOCKET} kill-server"
elif "$TMUX_BIN" -L "$TMUX_SOCKET" kill-server 2>/dev/null; then
    log_cleanup "Killed tmux server on socket '${TMUX_SOCKET}'"
else
    log_skip "tmux socket '${TMUX_SOCKET}' (no server running)"
fi

echo ""

echo "Removing local files..."
echo "--------------------------------------"

FILES_TO_DELETE=(
    ".env"
    "config.json"
    "totp-qr.png"
    "session_metadata.json"
    ".env.tmp"
)

for file in "${FILES_TO_DELETE[@]}"; do
    nuke_path "${PROJECT_ROOT}/${file}" "File: ${file}"
done

nuke_path "${PROJECT_ROOT}/venv" "Directory: venv/"

echo ""

echo "Removing directories..."
echo "--------------------------------------"

LOG_DIR="${LOG_DIRECTORY:-${NUKE_TMP}/cloude-code-logs}"
PROJECTS_DIR="${DEFAULT_WORKING_DIR:-${NUKE_HOME}/carnivore-projects}"

LOG_DIR=$(eval echo "$LOG_DIR")
PROJECTS_DIR=$(eval echo "$PROJECTS_DIR")

nuke_path "$LOG_DIR" "Directory: $LOG_DIR"
nuke_path "$PROJECTS_DIR" "Directory: $PROJECTS_DIR"
for LEGACY_PROJECTS_DIR in "${NUKE_HOME}/carnivore-projects" "${NUKE_HOME}/cloude-projects"; do
    if [ "$LEGACY_PROJECTS_DIR" != "$PROJECTS_DIR" ]; then
        nuke_path "$LEGACY_PROJECTS_DIR" "Directory: $LEGACY_PROJECTS_DIR"
    fi
done

TMP_LOGS=(
    "${NUKE_TMP}/cloudecode-server.log"
    "${NUKE_TMP}/cloudecode-menubar.log"
    "${NUKE_TMP}/cloudecode-menubar-error.log"
    "${NUKE_TMP}/carnivore-menubar.log"
    "${NUKE_TMP}/carnivore-menubar-error.log"
    "${NUKE_TMP}/electron-test.log"
)

TMP_LOGS+=(
    "${NUKE_HOME}/Library/Logs/Carnivore/menubar.log"
    "${NUKE_HOME}/Library/Logs/Carnivore/menubar-error.log"
)

for log_file in "${TMP_LOGS[@]}"; do
    nuke_path "$log_file" "File: $log_file"
done

nuke_path "${NUKE_TMP}/cloude-app-extract" "Directory: ${NUKE_TMP}/cloude-app-extract"

echo ""

echo "Removing macOS LaunchAgent..."
echo "--------------------------------------"

LAUNCH_AGENTS=(
    "${NUKE_HOME}/Library/LaunchAgents/com.cloudecode.menubar.plist"
    "${NUKE_HOME}/Library/LaunchAgents/ai.carnivore.menubar.plist"
)
for LAUNCH_AGENT in "${LAUNCH_AGENTS[@]}"; do
    if [ -f "$LAUNCH_AGENT" ]; then
        if [ "$DRY_RUN" = "true" ]; then
            log_cleanup "[dry-run] would unload and remove: $LAUNCH_AGENT"
        else
            "$LAUNCHCTL_BIN" unload "$LAUNCH_AGENT" 2>/dev/null || true
            rm -f "$LAUNCH_AGENT"
            log_cleanup "Removed: $LAUNCH_AGENT"
        fi
    else
        log_skip "LaunchAgent: $(basename "$LAUNCH_AGENT")"
    fi
done

echo ""

echo "Removing application state..."
echo "--------------------------------------"

nuke_path "$STATE_DIR" "State directory: $STATE_DIR"

APP_SUPPORT_DIRS=(
    "${NUKE_HOME}/Library/Application Support/cloude-code-menubar"
    "${NUKE_HOME}/Library/Application Support/Carnivore Menubar"
    "${NUKE_HOME}/Library/Application Support/Cloude Code"
)

for APP_SUPPORT in "${APP_SUPPORT_DIRS[@]}"; do
    nuke_path "$APP_SUPPORT" "Directory: $APP_SUPPORT"
done

echo ""

NUKE_LOG="${NUKE_TMP}/cloudecode-nuke.log"
if [ "$SKIP_CONFIRM" = "true" ]; then
    log_unknown_target "left in place: ${NUKE_LOG} (the macOS app is still writing to it; it is overwritten on the next run)."
else
    nuke_path "$NUKE_LOG" "File: $NUKE_LOG"
fi

echo ""
echo "========================================"
if [ "$DRY_RUN" = "true" ]; then
    echo -e "${YELLOW}Dry run complete. Nothing was deleted.${NC}"
else
    echo -e "${GREEN}Cleanup Complete!${NC}"
fi
echo "========================================"
echo ""
echo "Summary of removed items:"
echo ""

for item in "${CLEANUP_LOG[@]}"; do
    echo "  - $item"
done

echo ""
if [ "$DRY_RUN" = "false" ]; then
    echo -e "${YELLOW}Your system has been reset to a fresh state.${NC}"
    echo ""
    echo "To set up Cloude Code again, run:"
    echo "  ./setup.sh"
fi
echo ""
