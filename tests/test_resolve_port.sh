#!/bin/bash

set -uo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${TEST_DIR}/.." && pwd -P)"
# shellcheck source=../scripts/resolve-port.sh
source "${REPO_ROOT}/scripts/resolve-port.sh"

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

INSTALL1="${WORK}/install1"
mkdir -p "${INSTALL1}"

OUT="$(resolve_port "${INSTALL1}")"
RC=$?
assert "${RC}" "case 1: resolve_port exits 0 when .env is absent"
assert "$([ "${OUT}" = "8000" ] && echo 0 || echo 1)" \
    "case 1: resolve_port prints DEFAULT_PORT (8000) when .env is absent"

INSTALL2="${WORK}/install2"
mkdir -p "${INSTALL2}"
printf 'HOST=0.0.0.0\n' > "${INSTALL2}/.env"

OUT="$(resolve_port "${INSTALL2}")"
RC=$?
assert "${RC}" "case 2: resolve_port exits 0 when .env has no PORT= line"
assert "$([ "${OUT}" = "8000" ] && echo 0 || echo 1)" \
    "case 2: resolve_port prints DEFAULT_PORT when .env has no PORT= line"

INSTALL3="${WORK}/install3"
mkdir -p "${INSTALL3}"
printf 'PORT=9123\n' > "${INSTALL3}/.env"

OUT="$(resolve_port "${INSTALL3}")"
RC=$?
assert "${RC}" "case 3: resolve_port exits 0 for a valid PORT= override"
assert "$([ "${OUT}" = "9123" ] && echo 0 || echo 1)" \
    "case 3: resolve_port honors a valid non-default PORT= override"

INSTALL4="${WORK}/install4"
mkdir -p "${INSTALL4}"
printf 'PORT=notaport\n' > "${INSTALL4}/.env"

OUT="$(resolve_port "${INSTALL4}" 2>"${WORK}/case4.stderr")"
RC=$?
assert "$([ "${RC}" -ne 0 ] && echo 0 || echo 1)" \
    "case 4: resolve_port exits non-zero for a non-numeric PORT="
assert "$([ -z "${OUT}" ] && echo 0 || echo 1)" \
    "case 4: resolve_port prints nothing on stdout for a non-numeric PORT= (never DEFAULT_PORT)"
assert "$(grep -q 'could not determine port' "${WORK}/case4.stderr" && echo 0 || echo 1)" \
    "case 4: resolve_port names the failure on stderr as could-not-determine, not a silent guess"

INSTALL5="${WORK}/install5"
mkdir -p "${INSTALL5}"
printf 'PORT=99999\n' > "${INSTALL5}/.env"

OUT="$(resolve_port "${INSTALL5}" 2>"${WORK}/case5.stderr")"
RC=$?
assert "$([ "${RC}" -ne 0 ] && echo 0 || echo 1)" \
    "case 5: resolve_port exits non-zero for an out-of-range PORT="
assert "$([ -z "${OUT}" ] && echo 0 || echo 1)" \
    "case 5: resolve_port prints nothing on stdout for an out-of-range PORT="

INSTALL6="${WORK}/install6"
mkdir -p "${INSTALL6}"
printf 'PORT=\n' > "${INSTALL6}/.env"

OUT="$(resolve_port "${INSTALL6}")"
RC=$?
assert "${RC}" "case 6: resolve_port exits 0 for an empty PORT= value"
assert "$([ "${OUT}" = "8000" ] && echo 0 || echo 1)" \
    "case 6: resolve_port treats an empty PORT= as no override (DEFAULT_PORT)"

INSTALL7="${WORK}/install7"
mkdir -p "${INSTALL7}"
printf 'PORT=7001\n' > "${INSTALL7}/.env"
OUT="$(PORT=7002 resolve_port "${INSTALL7}")"
assert "$([ "${OUT}" = "7002" ] && echo 0 || echo 1)" "case 7: a PORT in the process environment wins over .env"

OUT="$(PORT=7003 resolve_port "${WORK}/no-such-install")"
assert "$([ "${OUT}" = "7003" ] && echo 0 || echo 1)" "case 8: a PORT in the process environment is honoured with no .env at all"

INSTALL9="${WORK}/install9"
mkdir -p "${INSTALL9}"
printf 'PORT=7004\nexport PORT=7005\n' > "${INSTALL9}/.env"
OUT="$(resolve_port "${INSTALL9}")"
assert "$([ "${OUT}" = "7005" ] && echo 0 || echo 1)" "case 9: the LAST PORT assignment wins and 'export PORT=' counts"

INSTALL10="${WORK}/install10"
mkdir -p "${INSTALL10}"
printf 'export PORT="7006"\n' > "${INSTALL10}/.env"
OUT="$(resolve_port "${INSTALL10}")"
assert "$([ "${OUT}" = "7006" ] && echo 0 || echo 1)" "case 10: a double-quoted exported PORT resolves"

printf "PORT='7007'\n" > "${INSTALL10}/.env"
OUT="$(resolve_port "${INSTALL10}")"
assert "$([ "${OUT}" = "7007" ] && echo 0 || echo 1)" "case 11: a single-quoted PORT resolves"

OUT="$(PORT=abc resolve_port "${INSTALL10}" 2>/dev/null)"
RC=$?
assert "$([ "${RC}" -ne 0 ] && [ -z "${OUT}" ] && echo 0 || echo 1)" "case 12: a malformed process-environment PORT fails loud, never DEFAULT_PORT"

PORT=7999
OUT="$(resolve_port "${INSTALL10}")"
assert "$([ "${OUT}" = "7007" ] && echo 0 || echo 1)" "case 13: an unexported shell variable PORT is ignored"
unset PORT

echo ""
if [ "${FAILURES}" -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "${FAILURES} FAILURE(S)"
    exit 1
fi
