#!/usr/bin/env bash
set -uo pipefail

MODE=master
GATE_MODE=warn
for arg in "$@"; do
    case "${arg}" in
        --branch) MODE=branch ;;
        --gate=refuse) GATE_MODE=refuse ;;
        --gate=warn) GATE_MODE=warn ;;
        *) echo "usage: web-build-check.sh [--branch] [--gate=refuse|warn]" >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${REPO_ROOT}/web"
DIST_DIR="${REPO_ROOT}/client/dist"

GENERATED_PATHS=(
    "${DIST_DIR}"
    "${REPO_ROOT}/hosted/catalog/admin/dist"
    "${REPO_ROOT}/FEATURES.md"
    "${REPO_ROOT}/features/index.json"
    "${REPO_ROOT}/features/schema.json"
)

EXPECTED_OUTPUTS=(app.js app.css style-guide.js popout.js popout.css pair.js pair.css widget-preview.js widget-preview.css widget-lab/widget-lab.js widget-lab/widget-lab.css)

fail_cannot_evaluate() {
    echo "web-build-check: CANNOT EVALUATE - $1" >&2
    echo "web-build-check: nothing was proven about client/dist." >&2
    exit 2
}

git_capture() {
    local __var="$1" __label="$2" __out __rc
    shift 2
    __out="$(git "$@" 2>/dev/null)"
    __rc=$?
    [ "${__rc}" -eq 0 ] || fail_cannot_evaluate "git ${__label} failed (exit ${__rc}); an empty answer would have read as clean"
    printf -v "${__var}" '%s' "${__out}"
}

[ -d "${WEB_DIR}" ] || fail_cannot_evaluate "no web/ directory at ${WEB_DIR}"
command -v node >/dev/null 2>&1 || fail_cannot_evaluate "node is not on PATH"
command -v npm  >/dev/null 2>&1 || fail_cannot_evaluate "npm is not on PATH"
command -v git  >/dev/null 2>&1 || fail_cannot_evaluate "git is not on PATH"

web_real="$(cd "${WEB_DIR}" 2>/dev/null && pwd -P)" \
    || fail_cannot_evaluate "cannot resolve the real path of ${WEB_DIR}"
repo_real="$(cd "${REPO_ROOT}" && pwd -P)"
case "${web_real}/" in
    "${repo_real}"/*) ;;
    *) fail_cannot_evaluate "web/ resolves to ${web_real}, which is outside this repo (${repo_real}); refusing rather than running npm ci against a checkout this run was not asked to check" ;;
esac

cd "${REPO_ROOT}" || fail_cannot_evaluate "cannot cd to ${REPO_ROOT}"

git_capture was_dirty_before "status of client/dist" status --porcelain -- "${DIST_DIR}"
current_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null)"

if [ "${MODE}" = "branch" ]; then
    if [ -n "${CLOUDE_WEB_CHECK_BASE:-}" ]; then
        base_ref="${CLOUDE_WEB_CHECK_BASE}"
    else
        # shellcheck source=scripts/lib/trunk-remote.sh
        . "${REPO_ROOT}/scripts/lib/trunk-remote.sh"
        trunk_remote="$(trunk_remote_name "${REPO_ROOT}")" || fail_cannot_evaluate \
            "could not resolve the trunk remote (set CLOUDE_TRUNK_REMOTE or CLOUDE_WEB_CHECK_BASE)"
        base_ref="${trunk_remote}/master"
    fi
    [ "${current_branch}" = "master" ] && fail_cannot_evaluate \
        "--branch on master proves nothing about the committed bundle; run it without --branch"
    git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null \
        || fail_cannot_evaluate "base ref ${base_ref} does not resolve (git fetch, or set CLOUDE_WEB_CHECK_BASE)"
    merge_base="$(git merge-base HEAD "${base_ref}" 2>/dev/null)" \
        || fail_cannot_evaluate "no merge base between HEAD and ${base_ref}"
    git_capture carried "diff against the merge base" diff --cached --name-only "${merge_base}" -- "${GENERATED_PATHS[@]}"
    if [ -n "${carried}" ]; then
        echo >&2
        echo "== BUNDLE CHANGE ON A BRANCH ==" >&2
        echo "this branch changes a generated file against its merge base with ${base_ref}:" >&2
        printf '%s\n' "${carried}" | sed 's/^/  /' >&2
        echo "Branches do not commit client/dist, hosted/catalog/admin/dist, FEATURES.md, features/index.json or" >&2
        echo "features/schema.json; scripts/dist-at-merge.sh builds all of them once, on" >&2
        echo "master, at merge time. Drop them from the branch:" >&2
        echo "  git restore --source=${merge_base} --staged --worktree -- client/dist hosted/catalog/admin/dist FEATURES.md features/index.json features/schema.json" >&2
        echo "  git commit -m 'drop generated files from the branch' -- client/dist hosted/catalog/admin/dist FEATURES.md features/index.json features/schema.json" >&2
        echo "(if ${base_ref} is stale, git fetch first and re-run.)" >&2
        exit 1
    fi
fi

if [ "${CLOUDE_WEB_CHECK_NO_INSTALL:-0}" != "1" ]; then
    if [ -L "${WEB_DIR}/node_modules" ]; then
        fail_cannot_evaluate "web/node_modules is a symlink (-> $(readlink "${WEB_DIR}/node_modules")). npm ci removes a symlink's TARGET before reinstalling, which can empty a node_modules directory another checkout still relies on. Replace it with a real, worktree-local copy first, e.g.: cp -Rc <source-repo>/web/node_modules ${WEB_DIR}/node_modules (or plain cp -R if your filesystem has no APFS clone-on-write), then re-run this check."
    fi
    echo "web-build-check: installing web/ dependencies from the lockfile ..."
    ( cd "${WEB_DIR}" && npm ci --no-fund --no-audit ) \
        || fail_cannot_evaluate "npm ci failed in web/"
fi

GATE="${REPO_ROOT}/scripts/design/check_top_down.sh"
[ -x "${GATE}" ] || fail_cannot_evaluate "no executable ${GATE}"
if [ "${MODE}" = "branch" ]; then
    ratchet_range="${merge_base}..HEAD"
elif git rev-parse --verify --quiet "refs/conformance/last-green^{commit}" >/dev/null \
        && git merge-base --is-ancestor refs/conformance/last-green HEAD 2>/dev/null; then
    ratchet_range="refs/conformance/last-green..HEAD"
elif git rev-parse --verify --quiet "HEAD~30^{commit}" >/dev/null; then
    ratchet_range="HEAD~30..HEAD"
else
    ratchet_range="$(git rev-list --max-parents=0 HEAD | tail -1)..HEAD"
fi
echo "web-build-check: running the top-down gate (ratchet range ${ratchet_range}) ..."
"${GATE}" --root "${REPO_ROOT}" --ratchet-range "${ratchet_range}"
gate_rc=$?
case "${gate_rc}" in
    0) ;;
    1) if [ "${GATE_MODE}" = "refuse" ]; then
           echo "web-build-check: TOP-DOWN GATE RED at $(git rev-parse --short HEAD); nothing was built." >&2
           exit 3
       fi
       echo "web-build-check: WARNING - the top-down gate is red at $(git rev-parse --short HEAD) (findings above). Not refusing: only the master landing refuses (--gate=refuse)." >&2 ;;
    *) if [ "${GATE_MODE}" = "refuse" ]; then
           fail_cannot_evaluate "the top-down gate could not run (exit ${gate_rc})"
       fi
       echo "web-build-check: WARNING - the top-down gate could not run (exit ${gate_rc}). Not refusing: only the master landing refuses (--gate=refuse)." >&2 ;;
esac

echo "web-build-check: building web/ into client/dist ..."
( cd "${WEB_DIR}" && npm run build ) \
    || fail_cannot_evaluate "the vite build failed"

missing=()
untracked=()
for name in "${EXPECTED_OUTPUTS[@]}"; do
    if [ ! -f "${DIST_DIR}/${name}" ]; then
        missing+=("client/dist/${name}")
        continue
    fi
    git ls-files --error-unmatch -- "${DIST_DIR}/${name}" >/dev/null 2>&1 \
        || untracked+=("client/dist/${name}")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo >&2
    echo "== BUNDLE INCOMPLETE ==" >&2
    echo "the build did not emit:" >&2
    printf '  %s\n' "${missing[@]}" >&2
    echo "Nothing was proven about the rest." >&2
    exit 2
fi
if [ "${MODE}" = "branch" ]; then
    echo
    echo "== BRANCH BUILDS =="
    echo "web/src builds, and the branch carries no client/dist change against ${base_ref}."
    echo "The fresh bundle is left unstaged for local tests. Do not commit it:"
    echo "scripts/dist-at-merge.sh builds it on master at merge time."
    exit 0
fi
if [ ${#untracked[@]} -gt 0 ]; then
    echo >&2
    echo "== BUNDLE NOT COMMITTED ==" >&2
    echo "these outputs exist but git does not track them, so a drift" >&2
    echo "check against the index can never see them move:" >&2
    printf '  %s\n' "${untracked[@]}" >&2
    echo "Commit them:  git add client/dist && git commit" >&2
    exit 1
fi

git_capture drift "status of client/dist after the rebuild" status --porcelain -- "${DIST_DIR}"
if [ -n "${drift}" ]; then
    echo >&2
    echo "== STALE BUNDLE ==" >&2
    echo "client/dist does not match what web/src builds to:" >&2
    printf '%s\n' "${drift}" >&2
    echo >&2
    if [ -n "${was_dirty_before}" ]; then
        echo "(it was already dirty before this rebuild, so it may simply" >&2
        echo " be an uncommitted build rather than a forgotten one.)" >&2
    fi
    echo "Commit the rebuilt bundle:  git add client/dist && git commit" >&2
    if [ "${current_branch}" != "master" ] && [ -n "${current_branch}" ]; then
        echo "(on a feature branch, run with --branch instead: branches do not" >&2
        echo " commit client/dist, scripts/dist-at-merge.sh builds it at merge.)" >&2
    fi
    exit 1
fi

echo
echo "== BUNDLE CURRENT =="
echo "client/dist matches what web/src builds to."
exit 0
