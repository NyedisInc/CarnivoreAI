#!/bin/bash

set -uo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${TEST_DIR}/.." && pwd -P)"
# shellcheck source=../scripts/deploy-lib.sh
source "${REPO_ROOT}/scripts/deploy-lib.sh"

FAILURES=0

assert() {
    local rc="$1" desc="$2"
    if [ "${rc}" -eq 0 ]; then
        printf 'PASS: %s\n' "${desc}"
    else
        printf 'FAIL: %s\n' "${desc}"
        FAILURES=$((FAILURES + 1))
    fi
}

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

FOUND1="${WORK}/found1.txt"
KEEP1="${WORK}/keep1.txt"
OUT1="${WORK}/out1.txt"
printf 'client/js/a.js\nclient/js/gone.js\nsrc/main.py\n' > "${FOUND1}"
printf 'client/js/a.js\nsrc/main.py\n' > "${KEEP1}"
dl_stale_paths "${FOUND1}" "${KEEP1}" "${OUT1}"
assert "$([ "$(cat "${OUT1}")" = "client/js/gone.js" ] && echo 0 || echo 1)" \
    "case 1: dl_stale_paths reports exactly the found-but-not-kept path"

INSCOPE="${WORK}/inscope.txt"
printf 'src/a.py\nclient/js/b.js\n' > "${INSCOPE}"
dl_reject_unscoped "${INSCOPE}" 2>/dev/null
assert "$?" "case 2a: dl_reject_unscoped passes a list entirely under src/ or client/"

OUTSCOPE="${WORK}/outscope.txt"
printf 'src/a.py\n.env\n' > "${OUTSCOPE}"
RC2B=0
dl_reject_unscoped "${OUTSCOPE}" 2>/dev/null || RC2B=$?
assert "$([ "${RC2B}" -ne 0 ] && echo 0 || echo 1)" \
    "case 2b: dl_reject_unscoped refuses a list containing a path outside src/ or client/"

TARGET3="${WORK}/target3"
mkdir -p "${TARGET3}/src/core" "${TARGET3}/client/js" "${TARGET3}/src/__pycache__"
echo x > "${TARGET3}/src/main.py"
echo x > "${TARGET3}/src/core/foo.py"
echo x > "${TARGET3}/client/js/app.js"
echo x > "${TARGET3}/src/__pycache__/main.cpython-312.pyc"
echo x > "${TARGET3}/src/stray.pyc"
echo x > "${TARGET3}/client/.DS_Store"
echo x > "${TARGET3}/.env"

FOUND3="${WORK}/found3.txt"
dl_find_tree "__local__" "${TARGET3}" "${FOUND3}"
EXPECTED3="$(printf 'client/js/app.js\nsrc/core/foo.py\nsrc/main.py\n')"
assert "$([ "$(cat "${FOUND3}")" = "${EXPECTED3}" ] && echo 0 || echo 1)" \
    "case 3a: dl_find_tree lists real files under src/ and client/, excluding __pycache__/*.pyc/.DS_Store"

NODEST="${WORK}/does-not-exist"
FOUND3B="${WORK}/found3b.txt"
dl_find_tree "__local__" "${NODEST}" "${FOUND3B}"
assert "$(grep -q '__NO_DEST__' "${FOUND3B}" && echo 0 || echo 1)" \
    "case 3b: dl_find_tree reports __NO_DEST__ for a destination that does not exist"

TARGET4="${WORK}/target4"
mkdir -p "${TARGET4}/src" "${TARGET4}/client/js"
echo x > "${TARGET4}/src/main.py"
echo x > "${TARGET4}/client/js/kept.js"
echo x > "${TARGET4}/client/js/removed.js"
echo x > "${TARGET4}/.env"

KEEP4="${WORK}/keep4.txt"
printf 'client/js/kept.js\nsrc/main.py\n' | LC_ALL=C sort > "${KEEP4}"

dl_prune_stale "__local__" "${TARGET4}" "${KEEP4}" 1 >/dev/null 2>&1
assert "$?" "case 4a: dl_prune_stale dry run exits 0"
assert "$([ -f "${TARGET4}/client/js/removed.js" ] && echo 0 || echo 1)" \
    "case 4b: dl_prune_stale dry run does NOT delete the stale file"

mkdir -p "${TARGET4}/src/__pycache__"
echo x > "${TARGET4}/src/__pycache__/main.cpython-312.pyc"

dl_prune_stale "__local__" "${TARGET4}" "${KEEP4}" 0 >/dev/null 2>&1
assert "$?" "case 5a: dl_prune_stale real run exits 0"
assert "$([ ! -e "${TARGET4}/client/js/removed.js" ] && echo 0 || echo 1)" \
    "case 5b: dl_prune_stale real run deletes the stale file"
assert "$([ -f "${TARGET4}/client/js/kept.js" ] && [ -f "${TARGET4}/src/main.py" ] && echo 0 || echo 1)" \
    "case 5c: dl_prune_stale real run leaves tracked files alone"
assert "$([ -f "${TARGET4}/.env" ] && echo 0 || echo 1)" \
    "case 5d: dl_prune_stale real run never touches a sibling outside src/ or client/"
assert "$([ -f "${TARGET4}/src/__pycache__/main.cpython-312.pyc" ] && echo 0 || echo 1)" \
    "case 5e: dl_prune_stale real run leaves __pycache__ noise alone (not its job)"

TARGET6="${WORK}/target6"
mkdir -p "${TARGET6}/src" "${TARGET6}/client"
echo x > "${TARGET6}/src/main.py"
echo x > "${TARGET6}/client/gone.js"
KEEP6="${WORK}/keep6.txt"
printf 'src/main.py\n' | LC_ALL=C sort > "${KEEP6}"

dl_verify_no_extra "__local__" "${TARGET6}" "${KEEP6}" "test target" 2>/dev/null
assert "$([ "$?" -eq 4 ] && echo 0 || echo 1)" \
    "case 6a: dl_verify_no_extra returns 4 while an untracked file remains"

rm -f "${TARGET6}/client/gone.js"
dl_verify_no_extra "__local__" "${TARGET6}" "${KEEP6}" "test target" 2>/dev/null
assert "$?" "case 6b: dl_verify_no_extra returns 0 once the target is mirror-clean"

dl_verify_no_extra "__local__" "${WORK}/nope" "${KEEP6}" "missing target" 2>/dev/null
assert "$([ "$?" -eq 3 ] && echo 0 || echo 1)" \
    "case 6c: dl_verify_no_extra returns 3 (cannot determine) for an unreadable destination"

assert "$([ "$(dl_combine_rc 0 0)" = "0" ] && echo 0 || echo 1)" \
    "case 7a: dl_combine_rc 0 0 -> 0"
assert "$([ "$(dl_combine_rc 0 3)" = "3" ] && echo 0 || echo 1)" \
    "case 7b: dl_combine_rc 0 3 -> 3 (cannot-determine beats success)"
assert "$([ "$(dl_combine_rc 3 4)" = "4" ] && echo 0 || echo 1)" \
    "case 7c: dl_combine_rc 3 4 -> 4 (definite failure beats cannot-determine)"
assert "$([ "$(dl_combine_rc 4 0)" = "4" ] && echo 0 || echo 1)" \
    "case 7d: dl_combine_rc 4 0 -> 4"

echo ""
if [ "${FAILURES}" -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "${FAILURES} FAILURE(S)"
    exit 1
fi
