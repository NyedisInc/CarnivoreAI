#!/bin/bash

trail_file() {
    resolve_state_file "$1" "migration_trail.jsonl"
}

trail_uuid() {
    local install_dir="$1" value python_bin
    if command -v uuidgen >/dev/null 2>&1; then
        value="$(uuidgen 2>/dev/null | tr 'A-Z' 'a-z')"
        if [ -n "${value}" ]; then
            printf '%s\n' "${value}"
            return 0
        fi
    fi
    python_bin="$(resolve_python "${install_dir}")"
    value="$("${python_bin}" -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)"
    [ -n "${value}" ] || return 1
    printf '%s\n' "${value}"
}

trail_now() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

trail_json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "${s}"
}

trail_json_value() {
    if [ -z "${1:-}" ]; then
        printf 'null'
    else
        printf '"%s"' "$(trail_json_escape "$1")"
    fi
}

trail_append_line() {
    local install_dir="$1" path="$2" line="$3" python_bin
    python_bin="$(resolve_python "${install_dir}")"
    "${python_bin}" - "${path}" "${line}" <<'PYEOF'
import os
import sys

path, line = sys.argv[1], sys.argv[2]
directory = os.path.dirname(path)
if directory:
    os.makedirs(directory, exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
try:
    os.write(fd, (line + "\n").encode("utf-8"))
    os.fsync(fd)
finally:
    os.close(fd)
PYEOF
    local rc=$?
    if [ "${rc}" -ne 0 ]; then
        log_fail "could not append to the migration trail at ${path} (rc=${rc})"
        return 1
    fi
    return 0
}

trail_code_line() {
    printf '{"entry_uuid": "%s", "kind": "code", "from_version": %s, "to_version": %s, "status": "%s", "started_at": "%s", "completed_at": %s, "backup_path": null, "backup_verified": null, "app_version": %s, "error": %s, "detail": %s}' \
        "$(trail_json_escape "$1")" \
        "$(trail_json_value "$3")" \
        "$(trail_json_value "$4")" \
        "$(trail_json_escape "$2")" \
        "$(trail_json_escape "$5")" \
        "$(trail_json_value "$6")" \
        "$(trail_json_value "$7")" \
        "$(trail_json_value "$8")" \
        "$(trail_json_value "$9")"
}

trail_code_open() {
    local install_dir="$1" from_v="$2" to_v="$3" app_v="$4" detail="$5"
    local path uuid started line
    path="$(trail_file "${install_dir}")"
    uuid="$(trail_uuid "${install_dir}")" || {
        log_fail "could not mint an entry_uuid for the migration trail"
        return 1
    }
    started="$(trail_now)"
    line="$(trail_code_line "${uuid}" "started" "${from_v}" "${to_v}" \
        "${started}" "" "${app_v}" "" "${detail}")"
    trail_append_line "${install_dir}" "${path}" "${line}" || return 1
    printf '%s %s\n' "${uuid}" "${started}"
}

trail_code_close() {
    local install_dir="$1" uuid="$2" started="$3" from_v="$4" to_v="$5"
    local status="$6" app_v="$7" error="$8"
    local path line completed
    path="$(trail_file "${install_dir}")"
    completed="$(trail_now)"
    line="$(trail_code_line "${uuid}" "${status}" "${from_v}" "${to_v}" \
        "${started}" "${completed}" "${app_v}" "${error}" "")"
    trail_append_line "${install_dir}" "${path}" "${line}"
}
