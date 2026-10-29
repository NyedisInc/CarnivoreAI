/* there is nothing */

(function () {
'use strict';

const CONFIG_EDITOR_ROOTS = [
    { id: 'user', label: '~/.claude', defaultExpanded: true },
    { id: 'workdir', label: 'project files', defaultExpanded: false },
];

/* not present in */
function resolveProjectContext(terminalController) {
    const tc = terminalController;
    if (!tc || !tc.sessionActive || !tc._currentSession) return { path: null, reason: 'no-session' };
    const s = tc._currentSession;
    const unwrapped = (s.session && typeof s.session === 'object') ? s.session : s;
    const workingDir = unwrapped && unwrapped.working_dir;
    if (!workingDir) return { path: null, reason: 'no-working-dir' };
    return { path: workingDir, reason: 'ok' };
}

/* no working directory */
function projectRootsNotice(reason) {
    if (reason === 'no-working-dir') {
        return 'the attached session reports no working directory, so '
            + 'project files cannot be listed.';
    }
    return null;
}

function workdirUnavailableNotice(label, projectPath) {
    const where = projectPath || 'the working directory';
    return `${label}: could not reach ${where} - it may have been moved, `
        + 'removed, or unmounted.';
}

function listErrorNotice(listError) {
    return `could not list contents: ${listError}`;
}

function expandFailedNotice(detail) {
    return `could not load contents: ${detail}`;
}

let rootPrefs = { showGlobal: true, topFolder: 'global' };

function setPrefs(next) {
    const clean = {
        showGlobal: !(next && next.showGlobal === false),
        topFolder: next && next.topFolder === 'project' ? 'project' : 'global',
    };
    const changed = clean.showGlobal !== rootPrefs.showGlobal || clean.topFolder !== rootPrefs.topFolder;
    rootPrefs = clean;
    return changed;
}

function getPrefs() {
    return { ...rootPrefs };
}

/* the project folder */
function visibleRoots(resolved, prefs = rootPrefs) {
    const listed = CONFIG_EDITOR_ROOTS.filter((def) => (def.id === 'user' ? prefs.showGlobal : resolved));
    const ordered = prefs.topFolder === 'project'
        ? [...listed.filter((d) => d.id !== 'user'), ...listed.filter((d) => d.id === 'user')]
        : listed;
    return ordered.length === 1 ? [{ ...ordered[0], defaultExpanded: true }] : ordered;
}

function planRoots(context, prefs = rootPrefs) {
    const resolved = !!(context && context.path);
    const plan = visibleRoots(resolved, prefs).map((def) => ({ kind: 'root', def }));
    if (!resolved) {
        const message = projectRootsNotice(context && context.reason);
        if (message) plan.push({ kind: 'notice', message });
    }
    return plan;
}

window.ConfigEditorRoots = {
    ROOTS: CONFIG_EDITOR_ROOTS,
    resolveProjectContext,
    projectRootsNotice,
    listErrorNotice,
    expandFailedNotice,
    workdirUnavailableNotice,
    planRoots,
    visibleRoots,
    setPrefs,
    getPrefs,
};
console.log('[ConfigEditorRoots Module] Exported as window.ConfigEditorRoots');

}());
