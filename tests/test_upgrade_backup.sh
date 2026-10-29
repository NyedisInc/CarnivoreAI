#!/bin/bash

set -uo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${TEST_DIR}/.." && pwd -P)"
# shellcheck source=../scripts/upgrade_lib/upgrade_rollback_common.sh
source "${REPO_ROOT}/scripts/upgrade_lib/upgrade_rollback_common.sh"

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
LOGDIR1="${WORK}/logs1"
mkdir -p "${INSTALL1}" "${LOGDIR1}"
printf 'CLOUDE_STATE_DIR=%s\nPORT=8000\n' "${LOGDIR1}" > "${INSTALL1}/.env"
echo '{"config_version": 1}' > "${INSTALL1}/config.json"
echo 'fake-refresh-token-db-bytes' > "${LOGDIR1}/refresh_tokens.db"
echo '{"session":"one"}' > "${LOGDIR1}/session_metadata.json"

BACKUP1="${WORK}/backup1"
OUT="$(take_backup "${INSTALL1}" "${BACKUP1}" 2>"${WORK}/case1.stderr")"
RC=$?
assert "${RC}" "case 1: take_backup exits 0 on a fully-configured install"
assert "$([ "${OUT}" = "${BACKUP1}" ] && echo 0 || echo 1)" "case 1: take_backup prints the backup dir"

assert "$(grep -q '^BACKED_UP	state	refresh_tokens.db	' "${BACKUP1}/.manifest" && echo 0 || echo 1)" \
    "case 1: refresh_tokens.db backed up from CLOUDE_STATE_DIR (not the install dir)"
assert "$(grep -q '^BACKED_UP	state	session_metadata.json	' "${BACKUP1}/.manifest" && echo 0 || echo 1)" \
    "case 1: session_metadata.json backed up from CLOUDE_STATE_DIR"
assert "$(grep -q '^NOT_PRESENT	state	pinned_themes.json$' "${BACKUP1}/.manifest" && echo 0 || echo 1)" \
    "case 1: pinned_themes.json recorded NOT_PRESENT (never pinned), not a failure"
assert "$(grep -q '^NOT_PRESENT	state	unread_state.json$' "${BACKUP1}/.manifest" && echo 0 || echo 1)" \
    "case 1: unread_state.json recorded NOT_PRESENT"
assert "$([ -f "${BACKUP1}/state/refresh_tokens.db" ] && echo 0 || echo 1)" \
    "case 1: refresh_tokens.db bytes actually present in the backup"
assert "$(cmp -s "${LOGDIR1}/refresh_tokens.db" "${BACKUP1}/state/refresh_tokens.db" && echo 0 || echo 1)" \
    "case 1: backed-up refresh_tokens.db is byte-identical to the source"


INSTALL2="${WORK}/install2"
LOGDIR2="${WORK}/logs2"
mkdir -p "${INSTALL2}" "${LOGDIR2}"
printf 'CLOUDE_STATE_DIR=%s\n' "${LOGDIR2}" > "${INSTALL2}/.env"
echo '{"config_version": 1}' > "${INSTALL2}/config.json"

BACKUP2="${WORK}/backup2"
( take_backup "${INSTALL2}" "${BACKUP2}" > "${WORK}/case2.stdout" 2>"${WORK}/case2.stderr" )
RC=$?
assert "$([ "${RC}" -ne 0 ] && echo 0 || echo 1)" \
    "case 2: take_backup DIES (non-zero exit) when a REQUIRED state file is missing"
assert "$(grep -q 'refresh_tokens.db' "${WORK}/case2.stderr" && echo 0 || echo 1)" \
    "case 2: the failure message names the missing file"


INSTALL3="${WORK}/install3"
mkdir -p "${INSTALL3}"

BACKUP3="${WORK}/backup3"
take_backup "${INSTALL3}" "${BACKUP3}" > "${WORK}/case3.stdout" 2>"${WORK}/case3.stderr"
RC=$?
assert "${RC}" "case 3: take_backup succeeds on a never-configured install"
assert "$(grep -q '^BACKED_UP' "${BACKUP3}/.manifest" && echo 1 || echo 0)" \
    "case 3: nothing is recorded BACKED_UP (there is nothing to back up yet)"


INSTALL4="${WORK}/install4"
mkdir -p "${INSTALL4}"
LOGDIR4_NEW="${WORK}/logs4_new"
mkdir -p "${LOGDIR4_NEW}"
printf 'CLOUDE_STATE_DIR=%s\n' "${LOGDIR4_NEW}" > "${INSTALL4}/.env"
echo '{"config_version": 4, "wrong": true}' > "${INSTALL4}/config.json"

echo 'CORRUPTED-BY-TEST' > "${LOGDIR1}/refresh_tokens.db"

restore_backup "${INSTALL4}" "${BACKUP1}" > "${WORK}/case4.stdout" 2>"${WORK}/case4.stderr"
RC=$?
assert "${RC}" "case 4: restore_backup exits 0"
assert "$(cmp -s "${INSTALL1}/.env" "${INSTALL4}/.env" && echo 0 || echo 1)" \
    "case 4: .env restored byte-identical to the original"
assert "$(cmp -s "${INSTALL1}/config.json" "${INSTALL4}/config.json" && echo 0 || echo 1)" \
    "case 4: config.json restored byte-identical to the original (overwrote the 'wrong' one)"
assert "$(cmp -s "${BACKUP1}/state/refresh_tokens.db" "${LOGDIR1}/refresh_tokens.db" && echo 0 || echo 1)" \
    "case 4: refresh_tokens.db restored into CLOUDE_STATE_DIR, overwriting the corrupted copy"
assert "$([ ! -f "${LOGDIR4_NEW}/refresh_tokens.db" ] && echo 0 || echo 1)" \
    "case 4: refresh_tokens.db NOT dumped into the stale/wrong log dir"


if ! command -v python3 >/dev/null 2>&1; then
    echo "SKIP: python3 not on PATH - cannot drive case 5's concurrent-writer scenario"
else
    C5_DIR="${WORK}/case5"
    mkdir -p "${C5_DIR}"
    C5_DB="${C5_DIR}/refresh_tokens.db"
    C5_READY="${C5_DIR}/.ready"
    C5_WRITING="${C5_DIR}/.writing"
    C5_GO="${C5_DIR}/.go"
    C5_DONE="${C5_DIR}/.done"

    python3 - "${C5_DB}" "${C5_READY}" "${C5_WRITING}" "${C5_GO}" "${C5_DONE}" <<'PYEOF' &
import sqlite3, sys, time, pathlib

db, ready, writing, go, done = sys.argv[1:6]

conn = sqlite3.connect(db, timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("CREATE TABLE t (x INTEGER)")
conn.execute("INSERT INTO t VALUES (1)")
conn.execute("INSERT INTO t VALUES (2)")
conn.execute("INSERT INTO t VALUES (3)")
conn.commit()
pathlib.Path(ready).touch()

conn.execute("BEGIN")
conn.execute("INSERT INTO t VALUES (4)")
conn.execute("INSERT INTO t VALUES (5)")
pathlib.Path(writing).touch()

waited = 0.0
while not pathlib.Path(go).exists() and waited < 20.0:
    time.sleep(0.05)
    waited += 0.05

conn.rollback()
conn.close()
pathlib.Path(done).touch()
PYEOF
    WRITER_PID=$!

    waited=0
    while [ ! -f "${C5_WRITING}" ] && [ "${waited}" -lt 200 ]; do
        sleep 0.05
        waited=$((waited + 1))
    done
    assert "$([ -f "${C5_WRITING}" ] && echo 0 || echo 1)" \
        "case 5 setup: background writer reached its held-open uncommitted transaction"

    C5_OUT_DIR="${C5_DIR}/backup-out"
    mkdir -p "${C5_OUT_DIR}"
    C5_DST="${C5_OUT_DIR}/refresh_tokens.db"
    ( _copy_sqlite "${C5_DB}" "${C5_DST}" ) 2>"${C5_DIR}/copy.stderr"
    COPY_RC=$?

    : > "${C5_GO}"
    wait "${WRITER_PID}" 2>/dev/null

    assert "${COPY_RC}" "case 5: _copy_sqlite succeeds against a live WAL-mode db with an open uncommitted writer"
    assert "$([ -f "${C5_DST}" ] && echo 0 || echo 1)" "case 5: destination file was created"

    C5_INTEGRITY="$(sqlite3 "${C5_DST}" 'PRAGMA integrity_check;' 2>/dev/null)"
    assert "$([ "${C5_INTEGRITY}" = "ok" ] && echo 0 || echo 1)" \
        "case 5: PRAGMA integrity_check on the copy reports ok (got: ${C5_INTEGRITY})"

    C5_COUNT="$(sqlite3 "${C5_DST}" 'SELECT COUNT(*) FROM t;' 2>/dev/null)"
    assert "$([ "${C5_COUNT}" = "3" ] && echo 0 || echo 1)" \
        "case 5: copy's row count is the COMMITTED count (3), not the uncommitted count (5) - got ${C5_COUNT}"
fi


C6_DIR="${WORK}/case6"
mkdir -p "${C6_DIR}"
C6_DB="${C6_DIR}/refresh_tokens.db"

python3 - "${C6_DB}" <<'PYEOF'
import sqlite3, sys, os
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("CREATE TABLE t (x INTEGER)")
conn.execute("INSERT INTO t VALUES (1)")
conn.execute("INSERT INTO t VALUES (2)")
conn.execute("INSERT INTO t VALUES (3)")
conn.commit()
os._exit(0)
PYEOF

assert "$([ -f "${C6_DB}-wal" ] && echo 0 || echo 1)" \
    "case 6 setup: the 3 commits landed in -wal, not yet checkpointed into the main file"

C6_CP_DST="${C6_DIR}/cp-copy.db"
cp -p "${C6_DB}" "${C6_CP_DST}"
C6_CP_COUNT="$(sqlite3 "${C6_CP_DST}" 'SELECT COUNT(*) FROM t;' 2>/dev/null)"

C6_VACUUM_DST="${C6_DIR}/vacuum-copy.db"
_copy_sqlite "${C6_DB}" "${C6_VACUUM_DST}"
C6_VACUUM_RC=$?
C6_VACUUM_COUNT="$(sqlite3 "${C6_VACUUM_DST}" 'SELECT COUNT(*) FROM t;' 2>/dev/null)"

assert "${C6_VACUUM_RC}" "case 6: _copy_sqlite succeeds"
assert "$([ "${C6_CP_COUNT}" != "${C6_VACUUM_COUNT}" ] && echo 0 || echo 1)" \
    "case 6: cp's row count ('${C6_CP_COUNT}') and VACUUM INTO's row count ('${C6_VACUUM_COUNT}') actually differ - the test can tell them apart"
assert "$([ -z "${C6_CP_COUNT}" ] || [ "${C6_CP_COUNT}" = "0" ] && echo 0 || echo 1)" \
    "case 6: cp lost all 3 uncheckpointed commits (empty/0 row count, got '${C6_CP_COUNT}') - this is the bug being fixed"
assert "$([ "${C6_VACUUM_COUNT}" = "3" ] && echo 0 || echo 1)" \
    "case 6: VACUUM INTO correctly reconciled the WAL and captured all 3 rows"


C7_DIR="${WORK}/case7"
mkdir -p "${C7_DIR}"
C7_SRC="${C7_DIR}/refresh_tokens.db"
python3 -c "
import sqlite3
conn = sqlite3.connect('${C7_SRC}')
conn.execute('CREATE TABLE t (x INTEGER)')
conn.execute('INSERT INTO t VALUES (1)')
conn.commit()
"
C7_DST="${C7_DIR}/copy.db"

( PATH="" _copy_sqlite "${C7_SRC}" "${C7_DST}" ) >"${C7_DIR}/out.stdout" 2>"${C7_DIR}/out.stderr"
RC=$?
assert "$([ "${RC}" -ne 0 ] && echo 0 || echo 1)" \
    "case 7: _copy_sqlite dies (non-zero exit) when sqlite3 is not on PATH"
assert "$(grep -q 'sqlite3 is not on PATH' "${C7_DIR}/out.stderr" && echo 0 || echo 1)" \
    "case 7: the failure message names the real cause (no sqlite3), not a generic error"
assert "$([ ! -e "${C7_DST}" ] && echo 0 || echo 1)" \
    "case 7: no destination file was left behind to be mistaken for a real backup"


C8_DIR="${WORK}/case8"
FAKEBIN="${C8_DIR}/fakebin"
mkdir -p "${FAKEBIN}"
REAL_SQLITE3="$(command -v sqlite3)"
cat > "${FAKEBIN}/sqlite3" <<EOF
#!/bin/bash
# Test double: forwards everything to the real sqlite3 EXCEPT
# integrity_check, which it fakes as corrupt - see case 8 in
# test_upgrade_backup.sh for why.
if [[ "\$*" == *"integrity_check"* ]]; then
    echo "corrupt-simulated-by-test-double"
    exit 0
fi
exec "${REAL_SQLITE3}" "\$@"
EOF
chmod +x "${FAKEBIN}/sqlite3"

C8_INSTALL="${C8_DIR}/install"
C8_LOGDIR="${C8_DIR}/logs"
mkdir -p "${C8_INSTALL}" "${C8_LOGDIR}"
printf 'CLOUDE_STATE_DIR=%s\n' "${C8_LOGDIR}" > "${C8_INSTALL}/.env"
echo '{"config_version": 1}' > "${C8_INSTALL}/config.json"
python3 -c "
import sqlite3
conn = sqlite3.connect('${C8_LOGDIR}/refresh_tokens.db')
conn.execute('CREATE TABLE t (x INTEGER)')
conn.commit()
"

C8_BACKUP="${C8_DIR}/backup"
( PATH="${FAKEBIN}:${PATH}" take_backup "${C8_INSTALL}" "${C8_BACKUP}" ) >"${C8_DIR}/out.stdout" 2>"${C8_DIR}/out.stderr"
RC=$?
assert "$([ "${RC}" -ne 0 ] && echo 0 || echo 1)" \
    "case 8: take_backup dies when a state file fails integrity_check"
assert "$(grep -q 'integrity_check' "${C8_DIR}/out.stderr" && echo 0 || echo 1)" \
    "case 8: the failure message names integrity_check as the cause"
if [ -f "${C8_BACKUP}/.manifest" ]; then
    assert "$(grep -q '^BACKED_UP.*refresh_tokens.db	' "${C8_BACKUP}/.manifest" && echo 1 || echo 0)" \
        "case 8: manifest never records BACKED_UP for the file that failed integrity_check"
else
    assert 0 "case 8: no manifest was even written before the fatal integrity failure (nothing to falsely mark BACKED_UP)"
fi

INSTALL10="${WORK}/install10"
NEWDIR10="${WORK}/state10-new"
OLDDIR10="${WORK}/state10-old"
BACKUP10="${WORK}/backup10"
mkdir -p "${INSTALL10}" "${NEWDIR10}" "${OLDDIR10}"
printf 'CLOUDE_STATE_DIR=%s\nLOG_DIRECTORY=%s\n' "${NEWDIR10}" "${OLDDIR10}" > "${INSTALL10}/.env"
echo '{}' > "${INSTALL10}/config.json"
echo 'old-refresh-token-db-bytes' > "${OLDDIR10}/refresh_tokens.db"
echo '{"old":true}' > "${OLDDIR10}/pinned_themes.json"

CLOUDE_STATE_DIR="" take_backup "${INSTALL10}" "${BACKUP10}" > "${WORK}/case10.out" 2> "${WORK}/case10.err"
CASE10_RC=$?

assert "${CASE10_RC}" \
    "case 10: take_backup SUCCEEDS when state files are at the old LOG_DIRECTORY location"
assert "$(grep -q '^BACKED_UP	state	refresh_tokens.db	' "${BACKUP10}/.manifest" && echo 0 || echo 1)" \
    "case 10: refresh_tokens.db backed up from the old location, not reported missing"
assert "$(cmp -s "${OLDDIR10}/refresh_tokens.db" "${BACKUP10}/state/refresh_tokens.db" && echo 0 || echo 1)" \
    "case 10: the bytes backed up are the OLD file's, not an empty new one"
assert "$(grep -q '^BACKED_UP	state	pinned_themes.json	' "${BACKUP10}/.manifest" && echo 0 || echo 1)" \
    "case 10: an optional JSON file at the old location is backed up too"
assert "$([ ! -f "${NEWDIR10}/refresh_tokens.db" ] && echo 0 || echo 1)" \
    "case 10: resolving the old location never creates anything at the new one"
assert "$(grep -q "^BACKED_UP	state	refresh_tokens.db	${OLDDIR10}$" "${BACKUP10}/.manifest" && echo 0 || echo 1)" \
    "case 10: the manifest records the OLD location as the origin, not the new state dir"

echo 'new-refresh-token-db-bytes' > "${NEWDIR10}/refresh_tokens.db"
RESOLVED10="$(resolve_state_file "${INSTALL10}" refresh_tokens.db)"
assert "$([ "${RESOLVED10}" = "${NEWDIR10}/refresh_tokens.db" ] && echo 0 || echo 1)" \
    "case 10: with the file in BOTH locations the new one wins (got ${RESOLVED10})"
assert "$([ -f "${OLDDIR10}/refresh_tokens.db" ] && echo 0 || echo 1)" \
    "case 10: the old copy is never deleted by resolution"


UPGRADE_SH="${REPO_ROOT}/scripts/upgrade.sh"
ROLLBACK_SH="${REPO_ROOT}/scripts/rollback.sh"

UPGRADE_STOP_LINE="$(grep -n '^stop_service "\${INSTALL_DIR}"' "${UPGRADE_SH}" | head -1 | cut -d: -f1)"
UPGRADE_BACKUP_LINE="$(grep -n 'take_backup "\${INSTALL_DIR}" "\${BACKUP_DIR}"' "${UPGRADE_SH}" | head -1 | cut -d: -f1)"
assert "$([ -n "${UPGRADE_STOP_LINE}" ] && [ -n "${UPGRADE_BACKUP_LINE}" ] && echo 0 || echo 1)" \
    "case 9: found both the stop_service and take_backup call sites in scripts/upgrade.sh"
assert "$([ "${UPGRADE_STOP_LINE}" -lt "${UPGRADE_BACKUP_LINE}" ] && echo 0 || echo 1)" \
    "case 9: scripts/upgrade.sh calls stop_service (line ${UPGRADE_STOP_LINE}) before take_backup (line ${UPGRADE_BACKUP_LINE})"

ROLLBACK_STOP_LINE="$(grep -n '^stop_service "\${INSTALL_DIR}"' "${ROLLBACK_SH}" | head -1 | cut -d: -f1)"
ROLLBACK_RESTORE_LINE="$(grep -n 'restore_backup "\${INSTALL_DIR}" "\${BACKUP_DIR}"' "${ROLLBACK_SH}" | head -1 | cut -d: -f1)"
assert "$([ -n "${ROLLBACK_STOP_LINE}" ] && [ -n "${ROLLBACK_RESTORE_LINE}" ] && echo 0 || echo 1)" \
    "case 9: found both the stop_service and restore_backup call sites in scripts/rollback.sh"
assert "$([ "${ROLLBACK_STOP_LINE}" -lt "${ROLLBACK_RESTORE_LINE}" ] && echo 0 || echo 1)" \
    "case 9: scripts/rollback.sh calls stop_service (line ${ROLLBACK_STOP_LINE}) before restore_backup (line ${ROLLBACK_RESTORE_LINE})"

echo ""
if [ "${FAILURES}" -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "${FAILURES} FAILURE(S)"
    exit 1
fi
