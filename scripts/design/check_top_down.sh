#!/usr/bin/env bash
set -uo pipefail

ROOT=""
RANGE=""
STAGED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT="${2:-}"; shift 2 ;;
        --ratchet-range) RANGE="${2:-}"; shift 2 ;;
        --staged) STAGED=1; shift ;;
        *) echo "usage: check_top_down.sh [--root DIR] [--ratchet-range A..B | --staged]" >&2; exit 2 ;;
    esac
done
[ -n "${ROOT}" ] || ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT="$(cd "${ROOT}" 2>/dev/null && pwd)" || { echo "top-down: CANNOT RUN - no directory ${ROOT}" >&2; exit 2; }
MANIFEST="${ROOT}/scripts/design/top_down_files.txt"
STARTED=$(date +%s)

cannot_run() {
    echo "top-down: CANNOT RUN - $1" >&2
    echo "top-down: nothing was proven (exit 2 is not a pass)." >&2
    exit 2
}

[ -f "${MANIFEST}" ] || cannot_run "no ${MANIFEST}"

VITEST_FILES=()
PYTEST_FILES=()
while read -r kind path _; do
    case "${kind}" in
        ''|\#*) continue ;;
        vitest) [ -f "${ROOT}/${path}" ] || cannot_run "listed check ${path} does not exist"; VITEST_FILES+=("${path#web/}") ;;
        pytest) [ -f "${ROOT}/${path}" ] || cannot_run "listed check ${path} does not exist"; PYTEST_FILES+=("${path}") ;;
        *) cannot_run "unknown line in ${MANIFEST}: ${kind} ${path}" ;;
    esac
done < "${MANIFEST}"
for f in "${ROOT}"/tests/python/design_system/test_*.py; do
    [ -f "${f}" ] || continue
    grep -qE "sync_playwright|from playwright|chromium" "${f}" && continue
    PYTEST_FILES+=("${f#"${ROOT}"/}")
done
[ ${#VITEST_FILES[@]} -gt 0 ] || cannot_run "no vitest check listed"
[ ${#PYTEST_FILES[@]} -gt 2 ] || cannot_run "no static design system test found under tests/python/design_system"

VITEST="${ROOT}/web/node_modules/.bin/vitest"
[ -x "${VITEST}" ] || cannot_run "no ${VITEST} (run: cd web && npm ci)"
PY=""
common_dir="$(git -C "${ROOT}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
for candidate in "${CARNIVORE_GATE_PYTHON:-}" "${ROOT}/venv/bin/python3" "${common_dir:+$(dirname "${common_dir}")/venv/bin/python3}"; do
    [ -n "${candidate}" ] && [ -x "${candidate}" ] || continue
    "${candidate}" -c "import pytest" >/dev/null 2>&1 || continue
    PY="${candidate}"
    break
done
[ -n "${PY}" ] || cannot_run "no python3 with pytest (looked at CARNIVORE_GATE_PYTHON, ${ROOT}/venv and the main checkout's venv)"

LOGS="$(mktemp -d "${TMPDIR:-/tmp}/top-down.XXXXXX")" || cannot_run "mktemp failed"
# shellcheck disable=SC2064  # expand now: remove THIS directory
trap "rm -rf '${LOGS}'" EXIT

VPID=""
PPID_=""

stop_runners() {
    local grace="${CARNIVORE_GATE_GRACE_S:-5}" i=0 groups=() pid
    for pid in "${VPID}" "${PPID_}"; do [ -n "${pid}" ] && groups+=("-${pid}"); done
    [ ${#groups[@]} -gt 0 ] || return 0
    kill -TERM -- "${groups[@]}" 2>/dev/null
    while [ -n "$(jobs -r)" ] && [ "${i}" -lt "${grace}" ]; do sleep 1; i=$((i + 1)); done
    sleep 1
    kill -KILL -- "${groups[@]}" 2>/dev/null
    { wait "${VPID}" "${PPID_}"; } 2>/dev/null
}

interrupted() {
    trap '' INT TERM HUP
    stop_runners
    exit "$1"
}
trap 'interrupted 130' INT
trap 'interrupted 143' TERM
trap 'interrupted 129' HUP

RUN_STARTED=$(date +%s)
set -m
( cd "${ROOT}/web" && exec "${VITEST}" run --reporter=default --testTimeout=0 --hookTimeout=0 "${VITEST_FILES[@]}" ) < /dev/null > "${LOGS}/vitest.log" 2>&1 &
VPID=$!
XDIST=()
"${PY}" -c "import xdist" >/dev/null 2>&1 && XDIST=(-n 4)
( cd "${ROOT}" && PYTHONDONTWRITEBYTECODE=1 exec "${PY}" -m pytest -v -p no:cacheprovider -rf ${XDIST[@]+"${XDIST[@]}"} "${PYTEST_FILES[@]}" ) < /dev/null > "${LOGS}/pytest.log" 2>&1 &
PPID_=$!
set +m

still_running() {
    local f names=""
    for f in "${VITEST_FILES[@]}"; do grep -qF -- " ${f} (" "${LOGS}/vitest.log" || names+=" ${f}"; done
    echo "  still running (vitest, no result yet):${names:- none}"
    names=" $(awk '
        function trim(x) { sub(/[ \t]+$/, "", x); return x }
        /^(\[gw[0-9]+\] \[ *[0-9]+%\] )?(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) [^ ]+::/ {
            id = $0; sub(/^(\[gw[0-9]+\] \[ *[0-9]+%\] )?[A-Z]+ /, "", id); done[trim(id)] = 1; next }
        /^[^ \[=][^ ]*::/ {
            if (match($0, / (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)( |$)/)) done[trim(substr($0, 1, RSTART - 1))] = 1
            else started[trim($0)] = 1 }
        END { for (id in started) if (!(id in done)) print id }' "${LOGS}/pytest.log" | sort | tr '\n' ' ')"
    for f in "${PYTEST_FILES[@]}"; do grep -qF -- "${f}::" "${LOGS}/pytest.log" || names+="${f} "; done
    echo "  still running (pytest, no result yet):${names% }"
}

DEADLINE_S="${CARNIVORE_GATE_DEADLINE_S:-900}"
while [ -n "$(jobs -r)" ]; do
    if [ $(( $(date +%s) - RUN_STARTED )) -ge "${DEADLINE_S}" ]; then
        stop_runners
        running="$(still_running)"
        {
            echo "== TOP-DOWN GATE COULD NOT RUN ($(( $(date +%s) - STARTED ))s) =="
            echo "  the runners were stopped at the ${DEADLINE_S}s deadline; a hang is exit 2, never a red."
            printf '%s\n' "${running}"
            tail -15 "${LOGS}/vitest.log" "${LOGS}/pytest.log" 2>/dev/null | sed 's/^/    | /'
        } >&2
        cannot_run "the runners took more than ${DEADLINE_S}s (CARNIVORE_GATE_DEADLINE_S) and were stopped; $(printf '%s' "${running}" | tr '\n' ';' | tr -s ' ' | sed 's/^ //')"
    fi
    sleep 1
done
wait "${VPID}"; VRC=$?
wait "${PPID_}"; PRC=$?

RED=()
UNRUN=()

v_failed="$(grep -E '^ FAIL ' "${LOGS}/vitest.log" | sed -E 's/^ FAIL +//' | sort -u)"
v_files_line="$(grep -E '^ +Test Files ' "${LOGS}/vitest.log" | tail -1)"
v_passed_files="$(printf '%s' "${v_files_line}" | sed -nE 's/.* ([0-9]+) passed.*/\1/p')"
v_failed_files="$(printf '%s' "${v_files_line}" | sed -nE 's/.*Test Files +([0-9]+) failed.*/\1/p')"
v_ran=$(( ${v_passed_files:-0} + ${v_failed_files:-0} ))
if [ -n "${v_failed}" ]; then
    while IFS= read -r line; do RED+=("vitest: ${line}"); done <<< "${v_failed}"
elif [ "${VRC}" -ne 0 ]; then
    UNRUN+=("vitest exited ${VRC} without naming a failure")
elif [ "${v_ran}" -ne ${#VITEST_FILES[@]} ]; then
    UNRUN+=("vitest ran ${v_ran} of ${#VITEST_FILES[@]} files")
fi

p_failed="$(grep -E '^(FAILED|ERROR) ' "${LOGS}/pytest.log" | sed -E 's/ - .*//' | sort -u)"
p_passed="$(grep -oE '[0-9]+ passed' "${LOGS}/pytest.log" | tail -1 | grep -oE '^[0-9]+')"
if [ "${PRC}" -eq 1 ] && [ -n "${p_failed}" ]; then
    while IFS= read -r line; do RED+=("pytest: ${line}"); done <<< "${p_failed}"
elif [ "${PRC}" -ne 0 ]; then
    UNRUN+=("pytest exited ${PRC}$( [ -n "${p_failed}" ] && printf ' (%s)' "$(printf '%s' "${p_failed}" | head -3 | tr '\n' ' ')")")
elif [ "${p_passed:-0}" -eq 0 ]; then
    UNRUN+=("pytest passed nothing")
fi

if [ -n "${RANGE}" ]; then
    "${PY}" "${ROOT}/scripts/design/ratchet_guard.py" --root "${ROOT}" --range "${RANGE}" > "${LOGS}/ratchet.log" 2>&1
    RRC=$?
    case "${RRC}" in
        0) ;;
        1) RED+=("ratchet: a KNOWN list, ceiling or baseline went up without Approved-by-other-operator (see below)") ;;
        *) UNRUN+=("ratchet guard exited ${RRC}") ;;
    esac
elif [ "${STAGED}" -eq 1 ]; then
    "${PY}" "${ROOT}/scripts/design/ratchet_guard.py" --root "${ROOT}" --staged > "${LOGS}/ratchet.log" 2>&1 \
        || UNRUN+=("ratchet guard could not read the index")
fi
[ -s "${LOGS}/ratchet.log" ] && sed 's/^/  /' "${LOGS}/ratchet.log" >&2

ELAPSED=$(( $(date +%s) - STARTED ))

if [ ${#RED[@]} -gt 0 ]; then
    echo >&2
    echo "== TOP-DOWN GATE RED (${ELAPSED}s) ==" >&2
    printf '  %s\n' "${RED[@]}" >&2
    [ ${#UNRUN[@]} -gt 0 ] && printf '  also could not run: %s\n' "${UNRUN[@]}" >&2
    paths="$(cat "${LOGS}/vitest.log" "${LOGS}/pytest.log" \
        | grep -oE '(web/src/|client/|tests/fixtures/)?(lib|opscenter|cplugs|widget-harness|style-guide|popout|admin|spectate|js|css)/[A-Za-z0-9_./-]+\.(svelte|ts|css|js|html|json)' \
        | grep -vE '\.(test|spec)\.[a-z]+$' | sort -u | head -40)"
    shown=0
    echo "  offenders and the commit that last touched each:" >&2
    while IFS= read -r p; do
        [ -n "${p}" ] || continue
        for cand in "${p}" "web/src/${p}" "client/${p}"; do
            if [ -f "${ROOT}/${cand}" ]; then
                echo "    ${cand}: $(git -C "${ROOT}" log -1 --date=short --format='%h %an %ad %s' -- "${cand}" 2>/dev/null | cut -c1-110)" >&2
                shown=$((shown + 1))
                break
            fi
        done
        [ "${shown}" -ge 12 ] && break
    done <<< "${paths}"
    [ "${shown}" -eq 0 ] && echo "    (the output names no source file; read the logs below)" >&2
    echo "  failure output (first 60 lines each):" >&2
    [ "${VRC}" -ne 0 ] && grep -vE '^\s*$' "${LOGS}/vitest.log" | grep -A12 -E 'FAIL |AssertionError|Expected|Received|^\+ ' | head -60 | sed 's/^/    | /' >&2
    [ "${PRC}" -ne 0 ] && grep -E '^E |^FAILED|^ERROR' "${LOGS}/pytest.log" | head -60 | sed 's/^/    | /' >&2
    exit 1
fi
if [ ${#UNRUN[@]} -gt 0 ]; then
    echo "== TOP-DOWN GATE COULD NOT RUN (${ELAPSED}s) ==" >&2
    printf '  %s\n' "${UNRUN[@]}" >&2
    tail -15 "${LOGS}/vitest.log" "${LOGS}/pytest.log" 2>/dev/null | sed 's/^/    | /' >&2
    cannot_run "see above"
fi
echo "== TOP-DOWN GATE GREEN (${ELAPSED}s): ${#VITEST_FILES[@]} vitest files, ${#PYTEST_FILES[@]} pytest files${RANGE:+, no unapproved ratchet raise in ${RANGE}} =="
exit 0
