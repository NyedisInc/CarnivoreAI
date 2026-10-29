#!/bin/bash

set -uo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${TEST_DIR}/.." && pwd -P)"

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

WORK="$(mktemp -d -t cloudemkdirlock)"
trap 'rm -rf "${WORK}"' EXIT


race_acquire() {
    local spelling="$1" lock="$2"
    bash -O expand_aliases -c '
        alias mkdir="mkdir -pv"
        spelling="$1"; lock="$2"
        if [ "$spelling" = "command mkdir" ]; then
            if command mkdir "$lock" >/dev/null 2>/dev/null; then echo WON; else echo LOST; fi
        else
            if mkdir "$lock" >/dev/null 2>/dev/null; then echo WON; else echo LOST; fi
        fi
    ' _ "$spelling" "$lock"
}

LOCK_BARE="${WORK}/lock-bare"
FIRST_BARE="$(race_acquire mkdir "${LOCK_BARE}")"
SECOND_BARE="$(race_acquire mkdir "${LOCK_BARE}")"
assert "$([ "${FIRST_BARE}" = WON ] && [ "${SECOND_BARE}" = WON ] && echo 0 || echo 1)" \
    "negative control: under alias mkdir='mkdir -pv', a bare 'mkdir \"\$LOCK\"' wrongly lets a SECOND acquirer win too (both must be WON - this reproduces issue #933's bug; if this assertion fails, the alias simulation stopped reproducing it and the rest of this file proves nothing)"

LOCK_FIXED="${WORK}/lock-fixed"
FIRST_FIXED="$(race_acquire "command mkdir" "${LOCK_FIXED}")"
SECOND_FIXED="$(race_acquire "command mkdir" "${LOCK_FIXED}")"
assert "$([ "${FIRST_FIXED}" = WON ] && [ "${SECOND_FIXED}" = LOST ] && echo 0 || echo 1)" \
    "fix: under the identical alias, 'command mkdir \"\$LOCK\"' lets only the FIRST acquirer win and correctly fails the second"


SKILL_MD="${REPO_ROOT}/.claude/skills/work/SKILL.md"
FULL_SUITE="${REPO_ROOT}/scripts/full-suite-master.sh"

for f in "${SKILL_MD}" "${FULL_SUITE}"; do
    assert "$([ -f "${f}" ] && echo 0 || echo 1)" "expected lock-acquire file exists: ${f#${REPO_ROOT}/}"
done

every_acquire_line_has_command() {
    local file="$1" line bad=0 seen=0
    while IFS= read -r line; do
        seen=$((seen + 1))
        case "${line}" in
            *"command mkdir"*) ;;
            *)
                printf 'missing "command" prefix in %s: %s\n' "${file#"${REPO_ROOT}"/}" "${line}" >&2
                bad=1
                ;;
        esac
    done < <(grep -E 'mkdir "\$LOCK(_DIR)?"([[:space:]]*2>/dev/null|.*\|\|)' "${file}")
    [ "${seen}" -gt 0 ] || { printf 'found no lock-acquire line at all in %s\n' "${file#"${REPO_ROOT}"/}" >&2; return 1; }
    return "${bad}"
}

assert "$(every_acquire_line_has_command "${SKILL_MD}"; echo $?)" \
    "every mkdir-lock-acquire line in .claude/skills/work/SKILL.md carries the command prefix"
assert "$(every_acquire_line_has_command "${FULL_SUITE}"; echo $?)" \
    "every mkdir-lock-acquire line in scripts/full-suite-master.sh carries the command prefix"

echo ""
if [ "${FAILURES}" -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "${FAILURES} FAILURE(S)"
    exit 1
fi
