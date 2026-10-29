#!/bin/bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/deploy-dmg.sh"
FAILED=0

FUNC_SRC=$(sed -n '/^wait_for_port_free() {$/,/^}$/p' "$SCRIPT")
if [ -z "$FUNC_SRC" ]; then
  echo "FAIL: could not extract wait_for_port_free from $SCRIPT"
  exit 1
fi

FAKEBIN="$(mktemp -d)"
trap 'rm -rf "$FAKEBIN"' EXIT
cat >"$FAKEBIN/lsof" <<'FAKE_LSOF'
#!/bin/bash
# Simulates lsof when nothing matches the filter: no output, exit 1.
exit 1
FAKE_LSOF
chmod +x "$FAKEBIN/lsof"

out=$(PATH="$FAKEBIN:$PATH" bash -c '
  set -euo pipefail
  POLL_S=0.2; POLL_TRIES=150
  '"$FUNC_SRC"'
  wait_for_port_free 8000
  echo "RETURNED_0"
' 2>&1)
rc=$?

if [ "$rc" -eq 0 ] && grep -qF "RETURNED_0" <<<"$out"; then
  echo "ok: wait_for_port_free returns 0 when lsof exits 1 (port free), under pipefail"
else
  echo "FAIL: wait_for_port_free did not return 0 when the port is free (rc=$rc)"
  echo "--- output ---"
  echo "$out"
  echo "--------------"
  FAILED=1
fi

if [ "$FAILED" -eq 0 ]; then
  echo "ALL PASS"
  exit 0
else
  echo "SOME TESTS FAILED"
  exit 1
fi
