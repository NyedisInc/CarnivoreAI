#!/bin/bash
#
#
#
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --state-dir)   STATE_DIR="$2";   shift 2 ;;
        -h|--help)     sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 64 ;;
    esac
done

PY="$INSTALL_DIR/venv/bin/python3"
[ -x "$PY" ] || PY="python3"

OUT_DIR="$INSTALL_DIR/.upgrade-baselines"
mkdir -p "$OUT_DIR"

CLOUDE_BASELINE_STATE_DIR="$STATE_DIR" \
CLOUDE_BASELINE_INSTALL_DIR="$INSTALL_DIR" \
CLOUDE_BASELINE_OUT_DIR="$OUT_DIR" \
"$PY" "$INSTALL_DIR/scripts/upgrade_snapshot.py" baseline
