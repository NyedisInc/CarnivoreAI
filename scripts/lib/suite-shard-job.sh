#!/usr/bin/env bash
set -u
SHA="${1:?sha}"; I="${2:?shard}"; N="${3:?count}"
CAP_IN="${BUMP_SHARD_CAPACITY:-}"; DUR_IN="${BUMP_SHARD_DURATIONS:-}"
D="$PWD/bump-shard-$I"; mkdir -p "$D"
PY="$PWD/venv/bin/python3"
if [ ! -L venv ]; then
    [ -x "$PY" ] || python3.12 -m venv venv || { echo "suite-shard-job: venv create failed (setup, not a test refusal)" >&2; exit 90; }
    want="$(cat requirements.txt requirements-dev.txt hosted/relay-control/requirements.txt | shasum -a 256 | cut -d' ' -f1)"
    if [ "$(cat venv/.reqs-stamp 2>/dev/null)" != "$want" ]; then
        RC_PURE="$(mktemp)"; grep -vE '^(cryptography|cffi)==' hosted/relay-control/requirements.txt > "$RC_PURE"
        "$PY" -m pip install -q -r requirements.txt -r requirements-dev.txt -r "$RC_PURE" || { rm -f "$RC_PURE"; echo "suite-shard-job: pip install failed (setup, not a test refusal)" >&2; exit 90; }
        rm -f "$RC_PURE"; echo "$want" > venv/.reqs-stamp
    fi
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
for pair in minisign:minisign gitleaks:gitleaks timeout:coreutils; do
    tool="${pair%%:*}"
    command -v "$tool" >/dev/null || { command -v brew >/dev/null && brew install "${pair##*:}" >/dev/null 2>&1; }
    command -v "$tool" >/dev/null || { echo "suite-shard-job: $tool is missing on $(hostname -s) and brew could not install it (setup, not a test refusal)" >&2; exit 90; }
done
for v in $(compgen -e | grep -E '^(CARNIVORE|CLOUDE|CLOUDECODE)_' | grep -v '^CLOUDE_HEAVY_RUN_'); do unset "$v"; done
unset TMUX TMUX_PANE HOST PORT BUMP_SHARD_CAPACITY BUMP_SHARD_DURATIONS
[ -x "$HOME/carnivore-suite/skew/tmux" ] && export CARNIVORE_SKEW_TMUX="$HOME/carnivore-suite/skew/tmux"
[ -n "$CAP_IN" ] && printf %s "$CAP_IN" > "$D/capacity.txt"
[ -n "$DUR_IN" ] && printf %s "$DUR_IN" > "$D/durations.json"
[ -f "$D/capacity.txt" ] && export CLOUDE_SHARD_CAPACITY="$(cat "$D/capacity.txt")"
[ -f "$D/durations.json" ] && export CLOUDE_SHARD_DURATIONS="$D/durations.json"
export CLOUDE_TEST_SHARD="$I/$N" CLOUDE_TEST_JUNIT_DIR="$D" CLOUDE_SUITE_STATE_DIR="$D/state" CLOUDE_SUITE_FAILURES_FILE="$D/failures"
export PYTHONPATH="$PWD/scripts/lib${PYTHONPATH:+:$PYTHONPATH}"
export PYTEST_ADDOPTS="-p suite_progress -rfE --durations=30 -o faulthandler_timeout=600 -m \"not mac_gui_session\""
"$PY" scripts/lib/suite_runner.py --log "$D/suite.log" --state-dir "$D/state" -- bash scripts/run-tests.sh
RC=$?
git rev-parse "HEAD^{tree}" > "$D/tree.txt" 2>/dev/null || rm -f "$D/tree.txt"
echo "$SHA" > "$D/sha.txt"
rm -rf "$D/state"
exit "$RC"
