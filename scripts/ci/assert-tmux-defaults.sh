#!/usr/bin/env bash
#
#
set -uo pipefail

readonly PROBE_SOCKET="cloude_ci_probe_$$"
readonly PROBE_SESSION="cloude_ci_probe_session"

if ! command -v tmux >/dev/null 2>&1; then
    echo "assert-tmux-defaults: tmux is not installed." >&2
    echo "  The tmux session-backend tests cannot run without it." >&2
    echo "  Install it (apt-get install tmux / brew install tmux) and retry." >&2
    exit 1
fi

cleanup() {
    tmux -L "${PROBE_SOCKET}" kill-server >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! tmux -L "${PROBE_SOCKET}" new-session -d -s "${PROBE_SESSION}" >/dev/null 2>&1; then
    echo "assert-tmux-defaults: could not start a detached tmux session." >&2
    exit 1
fi

window_index="$(tmux -L "${PROBE_SOCKET}" display-message -p -t "${PROBE_SESSION}" '#{window_index}' 2>/dev/null)"
pane_index="$(tmux -L "${PROBE_SOCKET}" display-message -p -t "${PROBE_SESSION}" '#{pane_index}' 2>/dev/null)"

status=0

if [ "${window_index}" != "0" ]; then
    echo "assert-tmux-defaults: window base-index is ${window_index}, expected 0." >&2
    echo "  tmux_backend.py targets '<session>:0.0'. Remove 'set -g base-index 1'" >&2
    echo "  from your tmux config, or expect the tmux tests to fail with" >&2
    echo "  \"can't find window: 0\"." >&2
    status=1
fi

if [ "${pane_index}" != "0" ]; then
    echo "assert-tmux-defaults: pane-base-index is ${pane_index}, expected 0." >&2
    echo "  Remove 'setw -g pane-base-index 1' from your tmux config." >&2
    status=1
fi

if [ "${status}" -eq 0 ]; then
    echo "assert-tmux-defaults: tmux $(tmux -V | awk '{print $2}') indexes windows and panes from 0"
fi

exit "${status}"
