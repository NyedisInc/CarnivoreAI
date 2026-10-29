#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
LIB_DIR="${SCRIPT_DIR}/roundtrip_lib"

OLD_REF="v0.8.1"
NEW_REF="integration/ui-only"
SOURCE_REPO="${REPO_ROOT}"
SEED_CONFIG="${REPO_ROOT}/tests/fixtures/roundtrip/old_config.json"
WORK_DIR=""
VENV_DIR=""
BASE_PORT=8137
KEEP=0

while [ $# -gt 0 ]; do
    case "$1" in
        --old) OLD_REF="$2"; shift 2 ;;
        --new) NEW_REF="$2"; shift 2 ;;
        --source-repo) SOURCE_REPO="$2"; shift 2 ;;
        --seed-config) SEED_CONFIG="$2"; shift 2 ;;
        --work-dir) WORK_DIR="$2"; shift 2 ;;
        --venv) VENV_DIR="$2"; shift 2 ;;
        --port) BASE_PORT="$2"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $1 (see --help)" >&2; exit 3 ;;
    esac
done

say()  { printf '[roundtrip] %s\n' "$*"; }
setup_fail() { printf '[roundtrip][SETUP-FAIL] %s\n' "$*" >&2; exit 3; }

[ "${BASE_PORT}" = "8000" ] && setup_fail "refusing base port 8000 - that is a real install"
[ "${BASE_PORT}" = "5000" ] && setup_fail "refusing port 5000 - AirPlay"

if [ -z "${WORK_DIR}" ]; then
    WORK_DIR="${HOME}/Scratch/scratch-lab/cc-roundtrip-run-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "${WORK_DIR}/artifacts" || setup_fail "cannot create work dir ${WORK_DIR}"
INSTALL="${WORK_DIR}/install"
STATE_DIR="${WORK_DIR}/state"
LOG_DIR="${WORK_DIR}/logs"
PROJ_DIR="${WORK_DIR}/projects"
mkdir -p "${STATE_DIR}" "${LOG_DIR}" "${PROJ_DIR}"

say "work dir:     ${WORK_DIR}"
say "source repo:  ${SOURCE_REPO}"
say "old ref:      ${OLD_REF}"
say "new ref:      ${NEW_REF}"
say "seed config:  ${SEED_CONFIG}"

[ -f "${SEED_CONFIG}" ] || setup_fail "seed config not found: ${SEED_CONFIG}"

PORT="$(python3 - "${BASE_PORT}" <<'PY'
import socket, sys
base = int(sys.argv[1])
for p in range(base, base + 200):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", p))
    except OSError:
        continue
    finally:
        s.close()
    print(p)
    break
PY
)"
[ -n "${PORT}" ] || setup_fail "no free port found from ${BASE_PORT}"
say "port:         ${PORT} (bound successfully before use)"

TMUX_BIN="${TMUX_BIN:-/opt/homebrew/bin/tmux}"
[ -x "${TMUX_BIN}" ] || TMUX_BIN="$(command -v tmux 2>/dev/null)"
META_SOCKET="roundtrip-meta-$$"
[ "${META_SOCKET}" = "cloude" ] && setup_fail "refusing to run on the production tmux socket"
say "tmux socket:  ${META_SOCKET} (throwaway; NEVER 'cloude')"

teardown_tmux() {
    [ -n "${TMUX_BIN}" ] || return 0
    [ "${META_SOCKET}" = "cloude" ] && return 0
    "${TMUX_BIN}" -L "${META_SOCKET}" kill-server >/dev/null 2>&1
    rm -f "${TMUX_TMPDIR:-/private/tmp}/tmux-$(id -u)/${META_SOCKET}" 2>/dev/null
    return 0
}
trap teardown_tmux EXIT

assert_socket_safe() {
    [ -f "${INSTALL}/config.json" ] || return 0
    python3 "${LIB_DIR}/pin_socket.py" "${INSTALL}/config.json" "${META_SOCKET}"
    [ $? -eq 0 ] || setup_fail "could not pin config.json to the throwaway tmux socket"
    return 0
}


git clone -q "${SOURCE_REPO}" "${INSTALL}" || setup_fail "clone of ${SOURCE_REPO} failed"
git -C "${INSTALL}" rev-parse --verify -q "${OLD_REF}^{commit}" >/dev/null \
    || setup_fail "old ref ${OLD_REF} does not exist in ${SOURCE_REPO}"
git -C "${INSTALL}" rev-parse --verify -q "${NEW_REF}^{commit}" >/dev/null \
    || git -C "${INSTALL}" rev-parse --verify -q "origin/${NEW_REF}^{commit}" >/dev/null \
    || setup_fail "new ref ${NEW_REF} does not exist in ${SOURCE_REPO}"


if [ -z "${VENV_DIR}" ]; then
    VENV_DIR="${WORK_DIR}/venv"
    say "building venv (both refs pin identical requirements)"
    python3 -m venv "${VENV_DIR}" >/dev/null 2>&1 || setup_fail "venv creation failed"
    "${VENV_DIR}/bin/pip" install -q --disable-pip-version-check \
        -r <(git -C "${INSTALL}" show "${NEW_REF}:requirements.txt" 2>/dev/null \
             || git -C "${INSTALL}" show "origin/${NEW_REF}:requirements.txt") \
        || setup_fail "pip install failed"
fi
PY_BIN="${VENV_DIR}/bin/python3"
[ -x "${PY_BIN}" ] || setup_fail "no python at ${PY_BIN}"
ln -sfn "${VENV_DIR}" "${INSTALL}/venv"

cat > "${INSTALL}/.env" <<EOF
HOST=127.0.0.1
PORT=${PORT}
DEFAULT_WORKING_DIR=${PROJ_DIR}
SESSION_TIMEOUT=3600
LOG_DIRECTORY=${LOG_DIR}
CLOUDE_STATE_DIR=${STATE_DIR}
AUTH_CONFIG_FILE=./config.json
TOTP_SECRET=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP
JWT_SECRET=roundtrip-harness-not-a-real-secret
EOF


checkout_ref() {
    local ref="$1"
    git -C "${INSTALL}" checkout -q --detach "${ref}" 2>/dev/null \
        || git -C "${INSTALL}" checkout -q --detach "origin/${ref}"
}

start_stop_server() {
    local out="$1.server.json"
    local log="$1.server.log"
    assert_socket_safe
    (
        cd "${INSTALL}" || exit 1
        exec "${PY_BIN}" -m src.main
    ) > "${log}" 2>&1 &
    local pid=$!
    local i=0
    local status="fail"
    local detail="server never answered /health within 45s"
    while [ $i -lt 90 ]; do
        if curl -fsS -m 2 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
            status="ok"
            detail="/health answered on port ${PORT}"
            break
        fi
        if ! kill -0 "${pid}" 2>/dev/null; then
            status="fail"
            detail="process exited before /health answered (see $(basename "${log}"))"
            break
        fi
        sleep 0.5
        i=$((i + 1))
    done
    if kill -0 "${pid}" 2>/dev/null; then
        kill "${pid}" 2>/dev/null
        local w=0
        while kill -0 "${pid}" 2>/dev/null && [ $w -lt 20 ]; do sleep 0.25; w=$((w + 1)); done
        kill -9 "${pid}" 2>/dev/null
    fi
    wait "${pid}" 2>/dev/null
    python3 - "${out}" "${status}" "${detail}" <<'PY'
import json, sys
open(sys.argv[1], "w").write(json.dumps(
    {"status": sys.argv[2], "detail": sys.argv[3]}, indent=2) + "\n")
PY
    return 0
}

STEP_N=0

capture_step() {
    local name="$1"
    local mode="${2:-server}"
    local expect="${3:-PASS}"
    STEP_N=$((STEP_N + 1))
    local prefix
    prefix="$(printf '%s/artifacts/%02d-%s' "${WORK_DIR}" "${STEP_N}" "${name}")"
    : > "${prefix}.step"
    printf '%s\n' "${expect}" > "${prefix}.expect"
    say "--- step $(printf '%02d' ${STEP_N}): ${name}"
    if [ "${mode}" != "noserver" ]; then
        start_stop_server "${prefix}"
    fi
    [ -f "${INSTALL}/config.json" ] && cp "${INSTALL}/config.json" "${prefix}.config.json"
    (
        cd "${INSTALL}" || exit 1
        "${PY_BIN}" "${LIB_DIR}/probe_install.py" \
            --install-dir "${INSTALL}" --label "${name}" --state-dir "${STATE_DIR}"
    ) > "${prefix}.probe.json" 2> "${prefix}.probe.err"
    python3 - "${prefix}.probe.json" <<'PY'
import json, sys
p = sys.argv[1]
raw = open(p).read()
start = raw.find("{")
if start < 0:
    sys.exit(0)
try:
    obj = json.loads(raw[start:])
except ValueError:
    sys.exit(0)
open(p, "w").write(json.dumps(obj, indent=2, sort_keys=True) + "\n")
PY
    return 0
}


checkout_ref "${OLD_REF}" || setup_fail "could not check out ${OLD_REF}"
cp "${SEED_CONFIG}" "${INSTALL}/config.json" || setup_fail "could not seed config.json"
capture_step "old-baseline"

say "--- exercising OLD write paths (save_project)"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" - <<'PY'
import sys
sys.path.insert(0, ".")
from src.config import Settings, ProjectConfig
s = Settings()
try:
    s.save_project(ProjectConfig(
        name="roundtrip-probe-project",
        path="~/projects/roundtrip-probe",
        description="written by the round-trip harness on the OLD version",
    ))
    print("OLD_WRITE_OK")
except Exception as e:
    print("OLD_WRITE_FAILED:", e)
PY
) > "${WORK_DIR}/artifacts/old-write.log" 2>&1
cat "${WORK_DIR}/artifacts/old-write.log" | tail -2

capture_step "old-after-write" noserver



say "--- creating real tmux sessions on ${META_SOCKET}"
if [ -n "${TMUX_BIN}" ]; then
    "${TMUX_BIN}" -L "${META_SOCKET}" new-session -d -s cloude_roundtrip-a -c "${PROJ_DIR}" "sleep 900" 2>/dev/null
    "${TMUX_BIN}" -L "${META_SOCKET}" new-session -d -s cloude_roundtrip-b -c "${PROJ_DIR}" "sleep 900" 2>/dev/null
    "${TMUX_BIN}" -L "${META_SOCKET}" list-sessions -F '#{session_name}' \
        > "${WORK_DIR}/artifacts/meta-tmux-sessions.txt" 2>&1
    say "sessions: $(tr '\n' ' ' < "${WORK_DIR}/artifacts/meta-tmux-sessions.txt")"
    grep -q '^cloude_' "${WORK_DIR}/artifacts/meta-tmux-sessions.txt" \
        || setup_fail "seeded tmux sessions are not cloude_-prefixed - the reconciler would read them as dead and this step would measure its own fixture"
else
    say "tmux not found - the metadata steps still run, tmux liveness is CANNOT DETERMINE"
    printf 'tmux-unavailable\n' > "${WORK_DIR}/artifacts/meta-tmux-sessions.txt"
fi

say "--- OLD version writes session_metadata.json at its own resolved path"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" "${LIB_DIR}/session_meta_probe.py" --label old-writes \
        --write roundtrip-a --name cloude_roundtrip-a \
        --working-dir "${PROJ_DIR}" --owned cloude_roundtrip-a --owned cloude_roundtrip-b
) > "${WORK_DIR}/artifacts/meta-01-old-writes.json" 2>&1
cat "${WORK_DIR}/artifacts/meta-01-old-writes.json"

checkout_ref "${NEW_REF}" || setup_fail "could not check out ${NEW_REF}"
capture_step "upgraded-new"

say "--- where the NEW version resolves session metadata after the upgrade"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" "${LIB_DIR}/session_meta_probe.py" --label new-after-upgrade
) > "${WORK_DIR}/artifacts/meta-02-new-after-upgrade.json" 2>&1
cat "${WORK_DIR}/artifacts/meta-02-new-after-upgrade.json"

say "--- exercising the NEW version's detach metadata sequence"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" "${LIB_DIR}/detach_probe.py"
) > "${WORK_DIR}/artifacts/meta-03-new-after-detach.json" 2> "${WORK_DIR}/artifacts/meta-03-new-after-detach.log"
cat "${WORK_DIR}/artifacts/meta-03-new-after-detach.json"


checkout_ref "${OLD_REF}" || setup_fail "could not check back out ${OLD_REF}"

say "--- what the OLD version resolves after the round trip (before it starts)"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" "${LIB_DIR}/session_meta_probe.py" --label old-after-downgrade
) > "${WORK_DIR}/artifacts/meta-04-old-after-downgrade.json" 2>&1
cat "${WORK_DIR}/artifacts/meta-04-old-after-downgrade.json"

capture_step "downgraded-old"

"${PY_BIN}" "${LIB_DIR}/meta_verdict.py" "${WORK_DIR}" > "${WORK_DIR}/artifacts/meta-verdict.json"
cat "${WORK_DIR}/artifacts/meta-verdict.json"
printf 'INTACT\n' > "${WORK_DIR}/artifacts/meta.expect"

say "--- exercising OLD write paths again, on the migrated config"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" - <<'PY'
import sys
sys.path.insert(0, ".")
from src.config import Settings, ProjectConfig
s = Settings()
try:
    s.save_project(ProjectConfig(
        name="roundtrip-probe-after-downgrade",
        path="~/projects/roundtrip-after",
        description="written by the OLD version AFTER the upgrade",
    ))
    print("OLD_WRITE_POST_UPGRADE_OK")
except Exception as e:
    print("OLD_WRITE_POST_UPGRADE_FAILED:", e)
PY
) > "${WORK_DIR}/artifacts/old-write-post.log" 2>&1
cat "${WORK_DIR}/artifacts/old-write-post.log" | tail -2

capture_step "downgraded-old-after-write" noserver


checkout_ref "${NEW_REF}" || setup_fail "could not re-check-out ${NEW_REF}"
capture_step "re-upgraded-new"


say "--- measuring DB-vs-config project agreement on the re-upgraded install"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" "${LIB_DIR}/db_vs_config_probe.py"
) > "${WORK_DIR}/artifacts/db-vs-config.json" 2> "${WORK_DIR}/artifacts/db-vs-config.err"
cat "${WORK_DIR}/artifacts/db-vs-config.json"


say "--- measuring what the migration does with a FUTURE config_version"
(
    cd "${INSTALL}" || exit 1
    "${PY_BIN}" "${LIB_DIR}/future_version_probe.py"
) > "${WORK_DIR}/artifacts/future-version.json" 2>&1
cat "${WORK_DIR}/artifacts/future-version.json"


say "--- injecting an object-form common_slash_commands entry (new-version-legal)"
"${PY_BIN}" - "${INSTALL}/config.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
cmds = d.get("common_slash_commands") or []
cmds.append({"command": "/diff", "description": "review changes"})
d["common_slash_commands"] = cmds
open(p, "w").write(json.dumps(d, indent=2) + "\n")
print("injected object-form entry; list length now", len(cmds))
PY
capture_step "new-with-object-slash-entry"
checkout_ref "${OLD_REF}" || setup_fail "could not check out ${OLD_REF} for the object-form step"
capture_step "downgraded-old-with-object-slash-entry" server FAIL


"${PY_BIN}" "${LIB_DIR}/report_roundtrip.py" --run-dir "${WORK_DIR}"
RC=$?

say "artifacts: ${WORK_DIR}/artifacts"
say "verdict:   ${WORK_DIR}/verdict.json"
if [ "${KEEP}" = "0" ] && [ "${RC}" = "0" ]; then
    say "run passed; work dir kept anyway for inspection (nothing here is deleted automatically)"
fi
exit ${RC}
