#!/bin/bash

INSTALL_REQUIRED_PAIR=(".env" "config.json")
INSTALL_OPTIONAL_FILES=("config.json.bak" ".update-check.json")
STATE_DIR_REQUIRED_FILES=("refresh_tokens.db")
STATE_DIR_OPTIONAL_FILES=("session_metadata.json" "pinned_themes.json" "unread_state.json" "carnivore.db" "cloude.db" "migration_trail.jsonl" "hook_tokens.json")

_URC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${_URC_DIR}/../resolve-port.sh"


log_ok() { printf '[OK]   %s\n' "$*" >&2; }

log_step() { printf '[STEP] %s\n' "$*" >&2; }

log_fail() { printf '[FAIL] %s\n' "$*" >&2; }

log_unknown() { printf '[UNKNOWN] %s\n' "$*" >&2; }

die() {
    log_fail "$*"
    exit 1
}


resolve_python() {
    local install_dir="$1" bundle arch candidate
    if [ -x "${install_dir}/venv/bin/python3" ]; then
        printf '%s\n' "${install_dir}/venv/bin/python3"
        return 0
    fi
    bundle="${CARNIVORE_APP_BUNDLE:-/Applications/Carnivore.app}"
    arch="$(uname -m)"
    for candidate in "${CARNIVORE_PAYLOAD_PYTHON:-}" "${bundle}/Contents/Resources/payload/payload-${arch}/python/bin/python3"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    die "no python found: no venv at ${install_dir}/venv, no payload python in ${bundle}, and no python3 on PATH - cannot run any check"
}


resolve_state_dir() {
    local install_dir="$1" python_bin
    local env_file="${install_dir}/.env"
    local raw="${CLOUDE_STATE_DIR:-}"
    if [ -z "${raw}" ] && [ -f "${env_file}" ]; then
        raw="$(grep -E '^CLOUDE_STATE_DIR=' "${env_file}" | tail -1 | cut -d= -f2-)"
    fi
    python_bin="$(resolve_python "${install_dir}")"
    if [ -n "${raw}" ]; then
        "${python_bin}" -c "import os, sys; print(os.path.expanduser(sys.argv[1]))" "${raw}"
    else
        "${python_bin}" -c "
import os
base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
current = os.path.join(base, 'Carnivore')
legacy = os.path.join(base, 'CloudeCode')
print(current if os.path.isdir(current) or not os.path.isdir(legacy) else legacy)
"
    fi
}

resolve_legacy_state_dir() {
    local install_dir="$1" python_bin raw
    local env_file="${install_dir}/.env"
    [ -f "${env_file}" ] || return 1
    raw="$(grep -E '^LOG_DIRECTORY=' "${env_file}" | tail -1 | cut -d= -f2-)"
    [ -n "${raw}" ] || return 1
    python_bin="$(resolve_python "${install_dir}")"
    "${python_bin}" -c "import os, sys; print(os.path.expanduser(sys.argv[1]))" "${raw}"
}

resolve_state_file() {
    local install_dir="$1" filename="$2" state_dir legacy_dir
    state_dir="$(resolve_state_dir "${install_dir}")"
    local new_path="${state_dir}/${filename}"

    local carnivore_legacy_path=""
    local raw="${CLOUDE_STATE_DIR:-}"
    if [ -z "${raw}" ] && [ -f "${install_dir}/.env" ]; then
        raw="$(grep -E '^CLOUDE_STATE_DIR=' "${install_dir}/.env" | tail -1 | cut -d= -f2-)"
    fi
    if [ -z "${raw}" ]; then
        local python_bin legacy_named_dir
        python_bin="$(resolve_python "${install_dir}")"
        legacy_named_dir="$("${python_bin}" -c "import os; print(os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'CloudeCode'))")"
        if [ "${legacy_named_dir}" != "${state_dir}" ]; then
            carnivore_legacy_path="${legacy_named_dir}/${filename}"
        fi
    fi

    legacy_dir="$(resolve_legacy_state_dir "${install_dir}")" || {
        if [ ! -f "${new_path}" ] && [ -n "${carnivore_legacy_path}" ] && [ -f "${carnivore_legacy_path}" ]; then
            printf '%s\n' "${carnivore_legacy_path}"
        else
            printf '%s\n' "${new_path}"
        fi
        return 0
    }
    local old_path="${legacy_dir}/${filename}"
    if [ -f "${new_path}" ]; then
        printf '%s\n' "${new_path}"
    elif [ -n "${carnivore_legacy_path}" ] && [ -f "${carnivore_legacy_path}" ]; then
        printf '%s\n' "${carnivore_legacy_path}"
    elif [ -f "${old_path}" ]; then
        printf '%s\n' "${old_path}"
    else
        printf '%s\n' "${new_path}"
    fi
}

require_git_root() {
    local install_dir="$1"
    if [ ! -d "${install_dir}/.git" ]; then
        die "${install_dir} is not a git checkout (no .git). This script only manages a from-source install (README Path B). A packaged .app install upgrades by downloading a new DMG - see the README."
    fi
    local toplevel
    toplevel="$(cd "${install_dir}" && git rev-parse --show-toplevel 2>/dev/null)" || die "git rev-parse failed in ${install_dir} - is git installed?"
    if [ "$(cd "${toplevel}" && pwd -P)" != "$(cd "${install_dir}" && pwd -P)" ]; then
        die "${install_dir} sits inside another repository's work tree (${toplevel}). Refusing - this is exactly the footgun src/core/version.py's is_git_root guards against."
    fi
}

require_clean_tree() {
    local install_dir="$1"
    local dirty
    dirty="$(cd "${install_dir}" && git status --porcelain --untracked-files=no)"
    if [ -n "${dirty}" ]; then
        log_fail "tracked files in ${install_dir} have local modifications:"
        printf '%s\n' "${dirty}" >&2
        die "commit, stash, or discard these before upgrading/rolling back - a dirty tree makes 'git checkout <tag>' unsafe to run unattended"
    fi
}


current_version() {
    local install_dir="$1" probe="$2" python_bin
    python_bin="$(resolve_python "${install_dir}")"
    "${python_bin}" "${probe}" current --install-dir "${install_dir}"
}

resolve_remote() {
    local install_dir="$1" probe="$2" python_bin config_arg=()
    python_bin="$(resolve_python "${install_dir}")"
    if [ -f "${install_dir}/config.json" ]; then
        config_arg=(--config "${install_dir}/config.json")
    fi
    "${python_bin}" "${probe}" remote --install-dir "${install_dir}" "${config_arg[@]}"
}


confirm_or_die() {
    local prompt="$1"
    if [ "${ASSUME_YES:-0}" = "1" ]; then
        log_step "non-interactive (--yes): proceeding without a prompt"
        return 0
    fi
    if [ ! -t 0 ]; then
        die "no terminal attached and --yes was not given - refusing to guess. Re-run with --yes for non-interactive use (e.g. from the menu bar app)."
    fi
    local reply
    read -r -p "${prompt} [type yes to continue] " reply
    if [ "${reply}" != "yes" ]; then
        die "not confirmed - no changes made"
    fi
}


_manifest_record() {
    if [ -n "${5:-}" ]; then
        printf '%s\t%s\t%s\t%s\n' "$2" "$3" "$4" "$5" >> "$1/.manifest"
    else
        printf '%s\t%s\t%s\n' "$2" "$3" "$4" >> "$1/.manifest"
    fi
}


_is_sqlite_file() {
    local f="$1"
    [ -f "${f}" ] && [ -s "${f}" ] || return 1
    local header
    header="$(head -c 15 "${f}" 2>/dev/null)"
    [ "${header}" = "SQLite format 3" ]
}

_copy_sqlite() {
    local src="$1" dst="$2"
    if ! command -v sqlite3 >/dev/null 2>&1; then
        die "sqlite3 is not on PATH - cannot take a verified backup of ${src}. Refusing to fall back to a raw file copy of a live SQLite database: see this file's SQLite-safe-copying note for why a plain cp of a WAL-mode database can capture a torn snapshot. Install sqlite3 (it ships with macOS and every Linux distro this fleet runs) and re-run."
    fi

    local dst_escaped="${dst//\'/\'\'}"
    local vacuum_err vacuum_rc
    vacuum_err="$(sqlite3 "${src}" "VACUUM INTO '${dst_escaped}';" 2>&1 1>/dev/null)"
    vacuum_rc=$?
    if [ "${vacuum_rc}" -ne 0 ]; then
        die "VACUUM INTO failed backing up ${src} to ${dst} (sqlite3 exit ${vacuum_rc}): ${vacuum_err}"
    fi

    local integrity integrity_rc
    integrity="$(sqlite3 "${dst}" "PRAGMA integrity_check;" 2>&1)"
    integrity_rc=$?
    if [ "${integrity_rc}" -ne 0 ] || [ "${integrity}" != "ok" ]; then
        rm -f "${dst}"
        die "backup of ${src} failed PRAGMA integrity_check (sqlite3 exit ${integrity_rc}, output: '${integrity}') - deleted the unverified copy at ${dst} rather than leaving it behind to be mistaken for a real backup. A VACUUM INTO that completes without erroring is not by itself proof the result is usable."
    fi
}

_copy_backup_file() {
    local src="$1" dst="$2"
    if _is_sqlite_file "${src}"; then
        _copy_sqlite "${src}" "${dst}"
        return 0
    fi
    cp -p "${src}" "${dst}"
}

take_backup() {
    local install_dir="$1" backup_dir="$2"
    if [ -e "${backup_dir}" ]; then
        die "backup directory ${backup_dir} already exists - refusing to overwrite a prior backup"
    fi
    mkdir -p "${backup_dir}/install" "${backup_dir}/state" || die "could not create backup directory ${backup_dir}"
    : > "${backup_dir}/.manifest"

    local env_present=0 config_present=0
    [ -f "${install_dir}/.env" ] && env_present=1
    [ -f "${install_dir}/config.json" ] && config_present=1

    if [ "${env_present}" -ne "${config_present}" ]; then
        die "half-configured install in ${install_dir}: .env present=${env_present}, config.json present=${config_present} - a broken install, refusing to guess which half is authoritative"
    fi

    local configured=0
    if [ "${env_present}" -eq 1 ]; then
        configured=1
        local f
        for f in "${INSTALL_REQUIRED_PAIR[@]}"; do
            _copy_backup_file "${install_dir}/${f}" "${backup_dir}/install/${f}" || die "failed to back up ${f}"
            _manifest_record "${backup_dir}" BACKED_UP install "${f}" "${install_dir}"
        done
    else
        log_unknown "${install_dir} has neither .env nor config.json - nothing has been configured yet (fresh checkout); backing up nothing, which is correct, not a failure"
    fi

    local f
    for f in "${INSTALL_OPTIONAL_FILES[@]}"; do
        if [ -f "${install_dir}/${f}" ]; then
            _copy_backup_file "${install_dir}/${f}" "${backup_dir}/install/${f}" || die "failed to back up ${f}"
            _manifest_record "${backup_dir}" BACKED_UP install "${f}" "${install_dir}"
        else
            _manifest_record "${backup_dir}" NOT_PRESENT install "${f}"
        fi
    done

    if [ "${configured}" -eq 1 ]; then
        local log_dir
        log_dir="$(resolve_state_dir "${install_dir}")"
        if [ -z "${log_dir}" ]; then
            die "${install_dir} is configured (.env present) but the state directory could not be resolved - refusing to back up blind. session_metadata.json, pinned_themes.json, unread_state.json, and refresh_tokens.db all live there and would be silently skipped otherwise."
        fi
        log_step "state directory (CLOUDE_STATE_DIR): ${log_dir}"

        local src
        for f in "${STATE_DIR_REQUIRED_FILES[@]}"; do
            src="$(resolve_state_file "${install_dir}" "${f}")"
            if [ -f "${src}" ]; then
                _copy_backup_file "${src}" "${backup_dir}/state/${f}" || die "failed to back up ${f} from ${src}"
                _manifest_record "${backup_dir}" BACKED_UP state "${f}" "$(dirname "${src}")"
                [ "${src}" = "${log_dir}/${f}" ] || log_step "${f} found at the pre-feat/state-directory location ${src} - backing up from there"
            else
                die "expected ${f} but it is in NEITHER the current state directory (${log_dir}) NOR the old LOG_DIRECTORY location. ${f} is created by every server startup, so either the server never started successfully on this install or state has already been lost. Refusing to take a partial backup and proceed with a destructive upgrade. If this install genuinely never ran, there is nothing to upgrade yet."
            fi
        done
        for f in "${STATE_DIR_OPTIONAL_FILES[@]}"; do
            src="$(resolve_state_file "${install_dir}" "${f}")"
            if [ -f "${src}" ]; then
                _copy_backup_file "${src}" "${backup_dir}/state/${f}" || die "failed to back up ${f} from ${src}"
                _manifest_record "${backup_dir}" BACKED_UP state "${f}" "$(dirname "${src}")"
            else
                _manifest_record "${backup_dir}" NOT_PRESENT state "${f}"
            fi
        done
    else
        log_unknown "skipping the state directory entirely - install was never configured, so its CLOUDE_STATE_DIR is unknown and nothing could exist there yet"
    fi

    local backed_up_count
    backed_up_count="$(grep -c '^BACKED_UP' "${backup_dir}/.manifest" || true)"
    printf '%s\n' "${backed_up_count:-0}" > "${backup_dir}/.file-count"
    log_ok "manifest: $(grep -c '^BACKED_UP' "${backup_dir}/.manifest" || echo 0) backed up, $(grep -c '^NOT_PRESENT' "${backup_dir}/.manifest" || echo 0) not present (see ${backup_dir}/.manifest)"
    printf '%s\n' "${backup_dir}"
}

restore_backup() {
    local install_dir="$1" backup_dir="$2"
    if [ ! -d "${backup_dir}" ]; then
        die "backup directory ${backup_dir} does not exist - cannot restore"
    fi
    if [ ! -f "${backup_dir}/.manifest" ]; then
        die "${backup_dir} has no .manifest - it was not produced by take_backup, refusing to trust it"
    fi

    local restored=0
    local outcome category name origin
    while IFS=$'\t' read -r outcome category name origin; do
        [ "${outcome}" = "BACKED_UP" ] || continue
        [ "${category}" = "install" ] || continue
        cp -p "${backup_dir}/install/${name}" "${install_dir}/${name}" || die "PARTIAL RESTORE: failed copying ${name} from ${backup_dir}/install - install_dir is now in a mixed state, ${restored} file(s) restored so far. Fix manually: diff ${backup_dir}/install ${install_dir}"
        restored=$((restored + 1))
    done < "${backup_dir}/.manifest"

    if awk -F'\t' '$1 == "BACKED_UP" && $2 == "state" { found = 1 }
                   END { exit found ? 0 : 1 }' "${backup_dir}/.manifest"; then
        local log_dir
        log_dir="$(resolve_state_dir "${install_dir}")"
        if [ -z "${log_dir}" ]; then
            die "PARTIAL RESTORE: install files restored (${restored}), but the state directory cannot be resolved from the just-restored .env, so session_metadata.json/pinned_themes.json/unread_state.json/refresh_tokens.db could NOT be restored. Fix .env's CLOUDE_STATE_DIR and re-run this script (idempotent) to finish."
        fi
        mkdir -p "${log_dir}" || die "could not create state directory ${log_dir} to restore state files into"
        local dest_dir
        while IFS=$'\t' read -r outcome category name origin; do
            [ "${outcome}" = "BACKED_UP" ] || continue
            [ "${category}" = "state" ] || continue

            if [ -n "${origin}" ]; then
                dest_dir="${origin}"
            else
                dest_dir="${log_dir}"
                log_unknown "${name}: this backup's manifest records no origin directory (written by an older take_backup), so where it was read FROM cannot be determined - restoring to the current state directory ${log_dir}. If this install predates feat/state-directory, check whether ${name} also needs to be at its LOG_DIRECTORY."
            fi
            mkdir -p "${dest_dir}" || die "PARTIAL RESTORE: could not create ${dest_dir} to restore ${name} into - ${restored} file(s) restored so far"
            cp -p "${backup_dir}/state/${name}" "${dest_dir}/${name}" || die "PARTIAL RESTORE: failed copying ${name} from ${backup_dir}/state to ${dest_dir} - ${restored} file(s) restored so far. Fix manually: diff ${backup_dir}/state ${dest_dir}"
            restored=$((restored + 1))
        done < "${backup_dir}/.manifest"
    fi

    printf '%s\n' "${restored}"
}


stop_service() {
    local install_dir="$1"
    if [ ! -x "${install_dir}/stop.sh" ]; then
        die "no executable stop.sh in ${install_dir}"
    fi
    (cd "${install_dir}" && ./stop.sh) || die "stop.sh exited non-zero - server may still be running, refusing to proceed with an upgrade against a live process"
}

start_service() {
    local install_dir="$1"
    if [ ! -x "${install_dir}/reset.sh" ]; then
        die "no executable reset.sh in ${install_dir}"
    fi
    (cd "${install_dir}" && ./reset.sh) || die "reset.sh exited non-zero - the server did not come back up. Check ${install_dir}/logs and CLOUDE_LAUNCHD_LABEL if this is a launchd-managed install."
}


verify_upgrade() {
    local install_dir="$1" port="$2" expected_version="$3" probe="$4"
    local timeout_s="${5:-20}"

    if ! command -v curl >/dev/null 2>&1; then
        log_unknown "curl is not on PATH - cannot verify the server answers. Check manually: open http://127.0.0.1:${port}/health"
        return 3
    fi

    local waited=0
    local health_ok=0
    while [ "${waited}" -lt "${timeout_s}" ]; do
        if curl -fsS --max-time 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
            health_ok=1
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done

    if [ "${health_ok}" -ne 1 ]; then
        log_fail "server did not answer http://127.0.0.1:${port}/health within ${timeout_s}s after restart"
        return 2
    fi
    log_ok "server answers on port ${port} (waited ${waited}s)"

    local actual_version
    actual_version="$(current_version "${install_dir}" "${probe}")"
    local rc=$?
    if [ "${rc}" -ne 0 ] || [ -z "${actual_version}" ]; then
        log_unknown "server is up, but the post-restart version could not be resolved - cannot confirm it is running ${expected_version}"
        return 3
    fi
    if [ "${actual_version}" != "${expected_version}" ]; then
        log_fail "server is up but reports version '${actual_version}', expected '${expected_version}'"
        return 2
    fi
    log_ok "server confirms version ${actual_version}"
    return 0
}
