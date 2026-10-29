#!/bin/bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="$ROOT/scripts/deploy-dmg.sh"
FAILED=0
FUNC_SRC=$(sed -n '/^list_cloude_sessions() {$/,/^}$/p' "$SCRIPT")
[ -n "$FUNC_SRC" ] || { echo "FAIL: cannot extract list_cloude_sessions"; exit 1; }

run() {
  ( set -euo pipefail; log() { echo "$*"; }; eval "$FUNC_SRC"
    CLOUDE_TMUX_SOCKET="$1" list_cloude_sessions ) 2>/dev/null
}

OUT=$(run "nosuch-$$-$RANDOM"); RC=$?
if [ "$RC" -eq 0 ] && [ -z "$OUT" ]; then echo "PASS: no server -> empty, exit 0"
else echo "FAIL: no server rc=$RC out='$OUT'"; FAILED=1; fi

FAKEBIN="$(mktemp -d)"; trap 'rm -rf "$FAKEBIN"' EXIT
printf '#!/bin/bash\necho "protocol version mismatch" >&2\nexit 1\n' >"$FAKEBIN/tmux"
chmod +x "$FAKEBIN/tmux"
OUT=$(PATH="$FAKEBIN:$PATH" run "nosuch-$$"); RC=$?
if [ "$RC" -ne 0 ]; then echo "PASS: other tmux error -> rc=$RC"
else echo "FAIL: other error swallowed"; FAILED=1; fi
exit "$FAILED"
