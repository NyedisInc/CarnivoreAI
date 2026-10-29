#!/usr/bin/env bash

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 90

PYTHON="$REPO_ROOT/venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    echo "run-tests.sh: $PYTHON is not executable. The system python3 has no" >&2
    echo "fastapi, so this is a refusal to run rather than a failure." >&2
    exit 90
fi

SERIAL_ONLY=(
    "tests/test_perf_harness_smoke.py"
    "tests/test_browser_real_chromium.py"
)

IGNORE_ARGS=()
for f in "${SERIAL_ONLY[@]}"; do
    if [ ! -f "$f" ]; then
        echo "run-tests.sh: $f is named for the serial pass but does not" >&2
        echo "exist. That would silently drop tests from the run, so this is" >&2
        echo "a refusal rather than a pass." >&2
        exit 90
    fi
    IGNORE_ARGS+=("--ignore=$f")
done

WORKERS="${CLOUDE_TEST_WORKERS:-6}"

J1=(); J2=(); JT=()
if [ -n "${CLOUDE_TEST_JUNIT_DIR:-}" ]; then
    J1=("--junitxml=$CLOUDE_TEST_JUNIT_DIR/pass1.xml")
    J2=("--junitxml=$CLOUDE_TEST_JUNIT_DIR/pass2.xml")
    JT=("--junitxml=$CLOUDE_TEST_JUNIT_DIR/targeted.xml")
fi

if [ "$#" -gt 0 ]; then
    echo "== targeted run at $WORKERS workers: $*"
    "$PYTHON" -m pytest -q -n "$WORKERS" ${JT[@]+"${JT[@]}"} "$@"
    RC_TARGETED=$?
    if [ "$RC_TARGETED" -eq 0 ]; then
        echo "run-tests.sh: PASS (targeted run, NOT the whole suite)"
    else
        echo "run-tests.sh: FAIL (targeted run, exit $RC_TARGETED)" >&2
    fi
    exit "$RC_TARGETED"
fi

# shellcheck source=scripts/lib/heavy-run-lock.sh
. "$REPO_ROOT/scripts/lib/heavy-run-lock.sh"
trap 'heavy_run_release' EXIT
trap 'heavy_run_release; exit 130' INT
trap 'heavy_run_release; exit 143' TERM
if ! heavy_run_acquire "$REPO_ROOT"; then
    echo "run-tests.sh: no heavy-run slot, so this is a refusal to run rather" >&2
    echo "than a failure. Raise CLOUDE_HEAVY_RUN_MAX_WAIT or wait for the holder." >&2
    exit 90
fi

echo "== pass 1 of 2: everything but the serial files, at $WORKERS workers"
"$PYTHON" -m pytest -q -n "$WORKERS" "${IGNORE_ARGS[@]}" ${J1[@]+"${J1[@]}"}
RC_PARALLEL=$?

echo
echo "== pass 2 of 2: ${SERIAL_ONLY[*]}, serially, on a quiet machine"
"$PYTHON" -m pytest -q ${J2[@]+"${J2[@]}"} "${SERIAL_ONLY[@]}"
RC_SERIAL=$?

echo
if [ "$RC_PARALLEL" -eq 0 ] && [ "$RC_SERIAL" -eq 0 ]; then
    echo "run-tests.sh: PASS (parallel pass 0, serial pass 0)"
    exit 0
fi

echo "run-tests.sh: FAIL (parallel pass $RC_PARALLEL, serial pass $RC_SERIAL)" >&2
if [ "$RC_PARALLEL" -ne 0 ]; then
    exit "$RC_PARALLEL"
fi
exit "$RC_SERIAL"
