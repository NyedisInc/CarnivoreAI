#!/usr/bin/env bash

set -u
SHA="${1:?sha}"; shift
BASE="$HOME/carnivore-suite"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
WT="$BASE/wt"; RUNS="$BASE/runs"; TOOLS="$BASE/tools"
if ! command -v minisign >/dev/null && command -v brew >/dev/null; then brew install minisign >/dev/null 2>&1; fi
if ! command -v timeout >/dev/null && command -v brew >/dev/null; then brew install coreutils >/dev/null 2>&1; fi
for c in git tmux node npm python3.12 minisign timeout rsync; do
    command -v "$c" >/dev/null || { echo "suite-host-run: $c is missing on $(hostname -s)" >&2; exit 2; }
done
[ -d "$WT/.git" ] || git clone -q "$BASE/repo.git" "$WT" || exit 2
git -C "$WT" fetch -q origin suite || exit 2
git -C "$WT" checkout -q --force --detach "$SHA" && git -C "$WT" clean -qfd || exit 2
find "$WT/packages" "$WT/cplugs" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
git -C "$WT" fetch -q origin '+refs/heads/master:refs/remotes/origin/master' || exit 2
git -C "$WT" fetch -q origin '+refs/tags/*:refs/tags/*' || exit 2
git -C "$WT" remote get-url trunk >/dev/null 2>&1 || git -C "$WT" remote add trunk https://github.com/trunk/CarnivoreAIDev.git
for d in "$HOME/dev-worktrees/catalog-ro" "$HOME/.cache/carnivore-payload/out"; do
    [ -d "$d" ] || { echo "suite-host-run: $d is missing on $(hostname -s) (full-suite-master.sh ships it from the owner computer)" >&2; exit 2; }
done
cp "$WT/config.example.json" "$WT/config.json"
ulimit -n 65536 2>/dev/null || ulimit -n "$(ulimit -Hn)" 2>/dev/null

stamp() { cat "$@" | shasum -a 256 | awk '{print $1}'; }
RC_REQ="$WT/hosted/relay-control/requirements.txt"
want="$(stamp "$WT/requirements.txt" "$WT/requirements-dev.txt" "$RC_REQ")"
if [ ! -x "$WT/venv/bin/python3" ] || [ "$(cat "$WT/venv/.reqs-stamp" 2>/dev/null)" != "$want" ]; then
    [ -x "$WT/venv/bin/python3" ] || python3.12 -m venv "$WT/venv" || exit 2
    RC_PURE="$(mktemp)"; grep -vE '^(cryptography|cffi)==' "$RC_REQ" > "$RC_PURE"
    "$WT/venv/bin/python3" -m pip install -q -r "$WT/requirements.txt" -r "$WT/requirements-dev.txt" -r "$RC_PURE" || { rm -f "$RC_PURE"; exit 2; }
    rm -f "$RC_PURE"
    echo "$want" > "$WT/venv/.reqs-stamp"
fi
for d in web macOS; do
    lock="$WT/$d/package-lock.json"; [ -f "$lock" ] || lock="$WT/$d/package.json"
    [ -f "$lock" ] || continue
    want="$(stamp "$lock")"
    if [ "$(cat "$WT/$d/node_modules/.suite-lock-stamp" 2>/dev/null)" != "$want" ] || [ ! -d "$WT/$d/node_modules" ]; then
        if [ -f "$WT/$d/package-lock.json" ]; then cmd=ci; else cmd=install; fi
        npm "$cmd" --prefix "$WT/$d" --no-audit --no-fund >/dev/null || exit 2
        echo "$want" > "$WT/$d/node_modules/.suite-lock-stamp"
    fi
done

mkdir -p "$RUNS"
rm -rf "$RUNS/junit" "$RUNS/suite.log" "$RUNS/suite.log.failures" "$RUNS/suite.log.flakes"; mkdir -p "$RUNS/junit"
: > "$RUNS/suite.log"
tail -F "$RUNS/suite.log" 2>/dev/null &
TAILPID=$!
(
    for v in $(compgen -e | grep -E '^(CARNIVORE|CLOUDE|CLOUDECODE)_' | grep -v '^CLOUDE_\(HEAVY_RUN_\|SUITE_\)'); do unset "$v"; done
    unset TMUX TMUX_PANE HOST PORT
    export CARNIVORE_SKEW_TMUX="$BASE/skew/tmux"
    export PYTHONPATH="$TOOLS${PYTHONPATH:+:$PYTHONPATH}" CLOUDE_SUITE_STATE_DIR="$RUNS/state" CLOUDE_SUITE_FAILURES_FILE="$RUNS/suite.log.failures"
    export PYTEST_ADDOPTS="-p suite_progress -rfE --durations=30 -o faulthandler_timeout=600 -m \"not mac_gui_session\""
    cd "$WT" && CLOUDE_TEST_JUNIT_DIR="$RUNS/junit" "$WT/venv/bin/python3" "$TOOLS/suite_runner.py" \
        --log "$RUNS/suite.log" --state-dir "$RUNS/state" -- bash "$WT/scripts/run-tests.sh" "$@"
    RC=$?
    if [ "$RC" -ne 0 ] && [ "$#" -eq 0 ]; then
        "$WT/venv/bin/python3" "$TOOLS/suite_rerun.py" --rc "$RC" --log "$RUNS/suite.log" \
            --failures "$RUNS/suite.log.failures" --flakes "$RUNS/suite.log.flakes" >> "$RUNS/suite.log" 2>&1
        RC=$?
    fi
    exit "$RC"
)
RC=$?
sleep 1; kill "$TAILPID" 2>/dev/null
exit "$RC"
