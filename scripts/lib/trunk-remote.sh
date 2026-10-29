#!/usr/bin/env bash
#
#

trunk_remote_name() {
    local dir="${1:-.}"
    local slug="${CLOUDE_TRUNK_REPO:-NyedisInc/CarnivoreAI}"
    local override="${CLOUDE_TRUNK_REMOTE:-}"

    if [ -n "${override}" ]; then
        if ! git -C "${dir}" remote get-url "${override}" >/dev/null 2>&1; then
            echo "trunk-remote: CLOUDE_TRUNK_REMOTE=${override} names no remote configured in ${dir} (see: git remote -v)" >&2
            return 1
        fi
        printf '%s\n' "${override}"
        return 0
    fi

    local remotes
    remotes="$(git -C "${dir}" remote 2>/dev/null)" \
        || { echo "trunk-remote: ${dir} is not a git checkout" >&2; return 1; }
    if [ -z "${remotes}" ]; then
        echo "trunk-remote: no remotes configured in ${dir}" >&2
        return 1
    fi

    local slug_lower; slug_lower="$(printf '%s' "${slug}" | tr '[:upper:]' '[:lower:]')"
    local name url norm norm_lower matched=() first_match=""
    for name in ${remotes}; do
        url="$(git -C "${dir}" remote get-url "${name}" 2>/dev/null)" || continue
        norm_lower="$(printf '%s' "${url}" | tr '[:upper:]' '[:lower:]')"
        case "${norm_lower}" in
            *.git) norm="${url:0:$((${#url} - 4))}" ;;
            *) norm="${url}" ;;
        esac
        norm="${norm%/}"
        norm_lower="$(printf '%s' "${norm}" | tr '[:upper:]' '[:lower:]')"
        case "${norm_lower}" in
            *"github.com:${slug_lower}"|*"github.com/${slug_lower}")
                matched+=("${name}")
                [ -z "${first_match}" ] && first_match="${name}"
                ;;
        esac
    done

    if [ "${#matched[@]}" -eq 0 ]; then
        echo "trunk-remote: no configured remote's fetch URL matches ${slug} (checked: $(printf '%s ' ${remotes}))" >&2
        echo "trunk-remote: add the remote, or override with CLOUDE_TRUNK_REMOTE=<name>" >&2
        return 1
    fi

    for name in "${matched[@]}"; do
        if [ "${name}" = "origin" ]; then
            printf 'origin\n'
            return 0
        fi
    done
    printf '%s\n' "${first_match}"
    return 0
}
