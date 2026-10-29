#!/bin/bash
#
#
#
#
#

TRAIL_SELECT_OK=0
TRAIL_SELECT_REFUSED=2
TRAIL_SELECT_UNREADABLE=3
TRAIL_SELECT_ABSENT=4

plan_data_rollback() {
    local install_dir="$1" target="$2" selector="$3" python_bin trail
    python_bin="$(resolve_python "${install_dir}")"
    trail="$(trail_file "${install_dir}")"
    "${python_bin}" "${selector}" select --trail "${trail}" --target-code "${target}"
}

plan_field() {
    local install_dir="$1" plan="$2" path="$3" python_bin
    python_bin="$(resolve_python "${install_dir}")"
    "${python_bin}" - "${plan}" "${path}" <<'PYEOF'
import json
import sys

plan, path = sys.argv[1], sys.argv[2]
try:
    node = json.loads(plan)
except ValueError:
    sys.exit(0)
for part in path.split("."):
    if isinstance(node, list):
        try:
            node = node[int(part)]
        except (ValueError, IndexError):
            sys.exit(0)
    elif isinstance(node, dict):
        if part not in node:
            sys.exit(0)
        node = node[part]
    else:
        sys.exit(0)
if node is None:
    sys.exit(0)
print(node)
PYEOF
}

plan_restores() {
    local install_dir="$1" plan="$2" python_bin
    python_bin="$(resolve_python "${install_dir}")"
    "${python_bin}" - "${plan}" <<'PYEOF'
import json
import sys

try:
    plan = json.loads(sys.argv[1])
except ValueError:
    sys.exit(0)
for item in plan.get("items", []):
    if item.get("outcome") == "restore":
        print("\t".join([item["kind"], item["artifact"], item["backup_path"]]))
PYEOF
}

warn_code_only() {
    local install_dir="$1" plan="$2" target="$3" schema_at cfg_at
    schema_at="$(plan_field "${install_dir}" "${plan}" "items.0.version_at_target")"
    cfg_at="$(plan_field "${install_dir}" "${plan}" "items.1.version_at_target")"
    echo "" >&2
    echo "==================================================================" >&2
    log_fail "--code-only: the DATA half of this rollback was SKIPPED"
    log_fail "code is being moved to ${target}; cloude.db and config.json are NOT being restored"
    if [ -n "${schema_at}" ]; then
        log_fail "the trail says schema was at v${schema_at} at ${target}; the database on disk is NOT being returned to it"
    else
        log_fail "the trail could not even say which schema version belonged to ${target}, so the size of this mismatch is unknown"
    fi
    if [ -n "${cfg_at}" ]; then
        log_fail "the trail says config was at v${cfg_at} at ${target}; config.json is NOT being returned to it"
    fi
    log_fail "expect the app to refuse writes and run DEGRADED READ-ONLY if the data is at a schema this code does not know."
    log_fail "GET /api/v1/version -> data.status will read degraded_schema_ahead and name both numbers."
    log_fail "to complete the rollback, re-run this script without --code-only."
    echo "==================================================================" >&2
    echo "" >&2
}

#
#
restore_one_artifact() {
    local install_dir="$1" artifact="$2" backup="$3"
    local dest snapshot stamp
    dest="$(resolve_state_file "${install_dir}" "${artifact}")"
    if [ "${artifact}" = "config.json" ]; then
        dest="${install_dir}/config.json"
    fi
    if [ ! -f "${backup}" ]; then
        log_fail "MISSING BACKUP: the trail names ${backup} as the backup to restore ${artifact} from, and that file is not on disk. Nothing has been changed and no snapshot was taken."
        return 1
    fi
    stamp="$(trail_now)"
    snapshot="${dest}.prerestore-${stamp}"
    if [ -f "${dest}" ]; then
        _copy_backup_file "${dest}" "${snapshot}" || {
            log_fail "could not snapshot the current ${artifact} to ${snapshot} - refusing to overwrite it"
            return 1
        }
        log_ok "current ${artifact} snapshotted to ${snapshot} (this script will never read it back; it is there for you)"
    else
        log_unknown "no current ${artifact} at ${dest} to snapshot - restoring onto nothing"
    fi
    cp -p "${backup}" "${dest}" || {
        log_fail "cp ${backup} -> ${dest} failed; ${artifact} may be partially written. The pre-restore snapshot is at ${snapshot}."
        return 1
    }
    rm -f "${dest}-wal" "${dest}-shm"
    log_ok "restored ${artifact} from $(basename "${backup}")"
}

#
#
locate_backup() {
    local install_dir="$1" state_dir="$2" name="$3" legacy
    case "${name}" in
        /*) printf '%s\n' "${name}"; return 0 ;;
    esac
    if [ -f "${state_dir}/${name}" ]; then
        printf '%s\n' "${state_dir}/${name}"
        return 0
    fi
    legacy="$(resolve_legacy_state_dir "${install_dir}")" && \
        if [ -f "${legacy}/${name}" ]; then
            printf '%s\n' "${legacy}/${name}"
            return 0
        fi
    if [ -f "${install_dir}/${name}" ]; then
        printf '%s\n' "${install_dir}/${name}"
        return 0
    fi
    printf '%s\n' "${state_dir}/${name}"
}

restore_data_half() {
    local install_dir="$1" plan="$2" state_dir="$3" count=0
    local line kind artifact backup_name backup_path
    while IFS=$'\t' read -r kind artifact backup_name; do
        [ -n "${kind}" ] || continue
        backup_path="$(locate_backup "${install_dir}" "${state_dir}" "${backup_name}")"
        restore_one_artifact "${install_dir}" "${artifact}" "${backup_path}" || return 1
        count=$((count + 1))
    done < <(plan_restores "${install_dir}" "${plan}")
    printf '%s\n' "${count}"
}
