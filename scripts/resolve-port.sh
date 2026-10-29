#!/bin/bash
#
#

DEFAULT_PORT=8000

resolve_port() {
    local install_dir="${1:-.}"
    local env_file="${install_dir}/.env"
    local raw source_desc

    raw="$(printenv PORT 2>/dev/null | tr -d '[:space:]' | tr -d "'\"")"
    source_desc="PORT in the process environment"
    if [ -z "${raw}" ] && [ -f "${env_file}" ]; then
        raw="$(grep -E '^[[:space:]]*(export[[:space:]]+)?PORT=' "${env_file}" | tail -1 | cut -d= -f2- | tr -d '[:space:]' | tr -d "'\"")"
        source_desc="PORT= in ${env_file}"
    fi

    if [ -z "${raw}" ]; then
        printf '%s\n' "${DEFAULT_PORT}"
        return 0
    fi

    case "${raw}" in
        ''|*[!0-9]*)
            printf 'could not determine port: %s (%s) is not a valid port number\n' "${source_desc}" "${raw}" >&2
            return 1
            ;;
    esac

    if [ "${raw}" -lt 1 ] || [ "${raw}" -gt 65535 ]; then
        printf 'could not determine port: %s (%s) is out of range (1-65535)\n' "${source_desc}" "${raw}" >&2
        return 1
    fi

    printf '%s\n' "${raw}"
    return 0
}

port_listener_pids() {
    lsof -nP -iTCP:"${1}" -sTCP:LISTEN -t 2>/dev/null || true
}

engine_pids_in_folders() {
    local folder p cwd
    local -a real=()
    for folder in "$@"; do
        folder="$(cd "${folder}" 2>/dev/null && pwd -P)" && real+=("${folder}")
    done
    [ "${#real[@]}" -gt 0 ] || return 0
    for p in $(pgrep -f 'src\.main' 2>/dev/null || true); do
        cwd="$(lsof -a -p "${p}" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
        for folder in "${real[@]}"; do
            if [ "${cwd}" = "${folder}" ]; then echo "${p}"; break; fi
        done
    done
}

port_own_listener_pids() {
    local port="$1" own listener
    shift
    own=" $(engine_pids_in_folders "$@" | tr '\n' ' ') "
    for listener in $(port_listener_pids "${port}"); do
        if [[ "${own}" == *" ${listener} "* ]]; then echo "${listener}"; fi
    done
}
