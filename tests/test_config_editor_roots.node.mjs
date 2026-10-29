
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => void} fn  Body; throwing marks the test failed.
 * @returns {void}
 */
function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function loadRoots() {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'config-editor-roots.js'),
        'utf8',
    );
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const context = { window: fakeWindow, console: { log() {} } };
    vm.createContext(context);
    vm.runInContext(src, context);
    return fakeWindow.ConfigEditorRoots;
}

const Roots = loadRoots();

function rootIds(plan) {
    return plain(plan).filter((s) => s.kind === 'root').map((s) => s.def.id);
}

function notices(plan) {
    return plain(plan).filter((s) => s.kind === 'notice').map((s) => s.message);
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

const WORKDIR = '/Users/someone/Development/project';

test('exactly two roots are declared, in order, with their labels, workdir collapsed by default', () => {
    assert.deepEqual(plain(Roots.ROOTS.map((r) => r.id)), ['user', 'workdir'],
        'the file editor drawer must show exactly two roots: user and workdir');
    const user = Roots.ROOTS.find((r) => r.id === 'user');
    assert.equal(user.label, '~/.claude');
    const workdir = Roots.ROOTS.find((r) => r.id === 'workdir');
    assert.equal(workdir.label, 'project files');
    assert.equal(workdir.defaultExpanded, false);
});

test('a SessionInfo WRAPPER resolves working_dir from .session', () => {
    const tc = { sessionActive: true, _currentSession: { session: { id: 'ses_1', working_dir: WORKDIR }, tmux_session: 'x' } };
    assert.deepEqual(plain(Roots.resolveProjectContext(tc)), { path: WORKDIR, reason: 'ok' });
});

test('a BARE Session resolves working_dir from the top level', () => {
    const tc = { sessionActive: true, _currentSession: { id: 'ses_1', working_dir: WORKDIR } };
    assert.deepEqual(plain(Roots.resolveProjectContext(tc)), { path: WORKDIR, reason: 'ok' });
});

test('no attached session reports reason no-session, not a bare null', () => {
    assert.deepEqual(plain(Roots.resolveProjectContext({ _currentSession: null, sessionActive: false })), { path: null, reason: 'no-session' });
    assert.deepEqual(plain(Roots.resolveProjectContext(null)), { path: null, reason: 'no-session' });
});

test('REGRESSION: a stale _currentSession from a detached session is not a project context on the launcher', () => {
    // not present in
    const tc = {
        sessionActive: false,
        _currentSession: { session: { id: 'ses_1', working_dir: WORKDIR } },
    };
    assert.deepEqual(plain(Roots.resolveProjectContext(tc)), { path: null, reason: 'no-session' });
});

test('an attached, active session resolves normally', () => {
    const tc = {
        sessionActive: true,
        _currentSession: { session: { id: 'ses_1', working_dir: WORKDIR } },
    };
    assert.deepEqual(plain(Roots.resolveProjectContext(tc)), { path: WORKDIR, reason: 'ok' });
});

test('an attached session with no working_dir is its OWN reason', () => {
    const tc = { sessionActive: true, _currentSession: { session: { id: 'ses_1' } } };
    assert.deepEqual(plain(Roots.resolveProjectContext(tc)), { path: null, reason: 'no-working-dir' });
});

test('REGRESSION: a resolved working dir plans both roots, no notice', () => {
    const plan = Roots.planRoots({ path: WORKDIR, reason: 'ok' });
    assert.deepEqual(rootIds(plan), ['user', 'workdir'],
        'workdir must be planned whenever the working directory resolved');
    assert.deepEqual(notices(plan), [], 'nothing to explain when every root is listed');
});

test('REGRESSION: no session on the launcher is a MEASURED absence - silent, no notice', () => {
    const plan = Roots.planRoots({ path: null, reason: 'no-session' });
    assert.deepEqual(rootIds(plan), ['user']);
    assert.deepEqual(notices(plan), [], 'the launcher with no project needs no explanation at all');
});

test('REGRESSION: an unresolvable working dir on an ATTACHED session is never silent', () => {
    const plan = Roots.planRoots({ path: null, reason: 'no-working-dir' });
    assert.deepEqual(rootIds(plan), ['user']);
    const msgs = notices(plan);
    assert.equal(msgs.length, 1);
    assert.match(msgs[0], /no working directory/);
    assert.match(msgs[0], /project files/);
});

test('only the could-not-evaluate reason carries a notice; the measured-absence reason does not', () => {
    assert.deepEqual(notices(Roots.planRoots({ path: null, reason: 'no-session' })), []);
    assert.equal(notices(Roots.planRoots({ path: null, reason: 'no-working-dir' })).length, 1);
});

test('workdirUnavailableNotice names the root and the directory, and reads as could-not-evaluate', () => {
    const msg = Roots.workdirUnavailableNotice('project files', WORKDIR);
    assert.match(msg, /project files/);
    assert.ok(msg.includes(WORKDIR), 'the notice must say WHERE it looked');
    assert.match(msg, /could not reach/, 'must read as could-not-evaluate, not a measured absence');
});

test('REGRESSION: no notice function narrates a project with no .claude/ or an empty root', () => {
    // nothing to list in
    assert.equal(Roots.missingRootNotice, undefined, 'missingRootNotice must be removed, not just unused');
    for (const key of Object.keys(Roots)) {
        const fn = Roots[key];
        if (typeof fn !== 'function' || fn.length === 0) continue;
        let sample;
        try {
            sample = key === 'workdirUnavailableNotice'
                ? fn('project files', WORKDIR)
                : key === 'projectRootsNotice' ? fn('no-working-dir')
                    : key === 'listErrorNotice' ? fn('Permission denied')
                        : null;
        } catch (_) { sample = null; }
        if (typeof sample !== 'string') continue;
        assert.ok(!/not present in/.test(sample), `${key} must never produce the removed "not present in" copy`);
        assert.ok(!/nothing to list in/.test(sample), `${key} must never produce the removed "nothing to list in" copy`);
    }
});

test('copy stays in the lowercase UI voice, with no dashes or emoji', () => {
    const strings = [
        Roots.projectRootsNotice('no-working-dir'),
        Roots.workdirUnavailableNotice('project files', WORKDIR),
    ];
    for (const s of strings) {
        assert.ok(s, 'every could-not-evaluate state needs a sentence');
        assert.ok(!/[–—]/.test(s), `no en/em dashes: ${s}`);
        assert.ok(!/[A-Z]/.test(s.replace(WORKDIR, '')), `lowercase copy: ${s}`);
    }
    assert.equal(Roots.projectRootsNotice('ok'), null, 'ok has nothing to say');
    assert.equal(Roots.projectRootsNotice('no-session'), null, 'no-session is a measured absence, not a sentence');
});

test('the panel reads its root table and plan from this module', () => {
    const panel = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'config-editor-panel.js'),
        'utf8',
    );
    assert.ok(!/const CONFIG_EDITOR_ROOTS/.test(panel),
        'the panel must not keep a second copy of the root table');
    assert.ok(panel.includes('window.ConfigEditorRoots.visibleRoots'),
        'the new-file prompt must offer exactly the roots the tree shows');
    assert.ok(panel.includes('window.ConfigEditorRoots.planRoots'),
        'the panel must render the plan, not re-derive which roots to skip');
    assert.ok(!/continue; \/\/ no session attached/.test(panel),
        'the silent continue that dropped both project roots must stay gone');
});

test('module-families.js loads the roots module before the panel', () => {
    const families = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'module-families.js'),
        'utf8',
    );
    const roots = families.indexOf("'/static/js/config-editor-roots.js'");
    const panel = families.indexOf("'/static/js/config-editor-panel.js'");
    assert.ok(roots !== -1, 'config-editor-roots.js must be listed in the CONFIG_EDITOR family');
    assert.ok(panel !== -1, 'config-editor-panel.js must be listed in the CONFIG_EDITOR family');
    assert.ok(roots < panel, 'the panel reads ConfigEditorRoots.ROOTS at definition time');
});

test('REGRESSION: roots.js and panel.js share a global scope without colliding', () => {
    const read = (name) => fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', name), 'utf8',
    );
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const context = {
        window: fakeWindow,
        console: { log() {} },
        document: { createElement: () => ({ style: {} }) },
    };
    vm.createContext(context);
    vm.runInContext(read('config-editor-roots.js'), context);
    vm.runInContext(read('config-editor-panel.js'), context);
    assert.ok(fakeWindow.ConfigEditorPanel,
        'the panel must still define window.ConfigEditorPanel after roots.js loaded');
    assert.deepEqual(
        plain(fakeWindow.ConfigEditorRoots.ROOTS.map((r) => r.id)),
        ['user', 'workdir'],
    );
});


test('listErrorNotice names the failure, never reads like "empty"', () => {
    const s = Roots.listErrorNotice('Permission denied');
    assert.ok(s.includes('Permission denied'), 'must surface the actual reason');
    assert.ok(/could not/i.test(s), 'must say it could not evaluate, not that there is nothing');
    assert.ok(!/[–—]/.test(s), 'no en/em dashes');
});

test('REGRESSION: an unreadable node and a genuinely empty node render different strings', () => {
    const emptyDirRendering = null;
    const unreadableRendering = Roots.listErrorNotice('Permission denied');
    assert.notEqual(unreadableRendering, emptyDirRendering,
        'an unreadable directory must never render identically to an empty one');
});

test('list_error is rendered through the shared notice builder, not an inline string', () => {
    const lazy = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'config-editor-lazy.js'),
        'utf8',
    );
    assert.ok(lazy.includes('node.list_error'),
        'the expansion path must check TreeNode.list_error before rendering children');
    assert.ok(lazy.includes('window.ConfigEditorRoots.listErrorNotice(node.list_error)'),
        'the wording must come from the tested pure function, not a second inline copy');
});

test('an expansion that could not be answered says so, and not "empty"', () => {
    const failed = Roots.expandFailedNotice('locked could not be read: Permission denied');
    assert.ok(failed.length > 0, 'there must be a sentence at all');
    const ours = failed.replace('locked could not be read: Permission denied', '');
    assert.equal(ours, ours.toLowerCase(), 'ui copy is lowercase');
    assert.ok(!/empty/i.test(failed),
        'a could-not-load sentence must never claim the directory is empty');
    assert.notEqual(failed, Roots.listErrorNotice('Permission denied'),
        'a failed request and a server-reported list_error are different facts');
});

const RESOLVED = { path: WORKDIR, reason: 'ok' };

test('files widget settings: hiding the global folder lists only the project, open', () => {
    const plan = Roots.planRoots(RESOLVED, { showGlobal: false, topFolder: 'global' });
    assert.deepEqual(rootIds(plan), ['workdir']);
    assert.equal(plan[0].def.defaultExpanded, true, 'a lone root must open, not show a blank tree');
});

test('files widget settings: project on top reverses the order', () => {
    assert.deepEqual(rootIds(Roots.planRoots(RESOLVED, { showGlobal: true, topFolder: 'project' })), ['workdir', 'user']);
    assert.deepEqual(rootIds(Roots.planRoots(RESOLVED, { showGlobal: true, topFolder: 'global' })), ['user', 'workdir']);
});

test('files widget settings: hiding global with no project is an empty plan and the notice is kept', () => {
    const plan = Roots.planRoots({ path: null, reason: 'no-working-dir' }, { showGlobal: false, topFolder: 'global' });
    assert.deepEqual(rootIds(plan), []);
    assert.equal(notices(plan).length, 1);
    assert.deepEqual(rootIds(Roots.planRoots({ path: null, reason: 'no-session' }, { showGlobal: false, topFolder: 'global' })), []);
});

test('files widget settings: setPrefs drives the default plan, reports a change, and sanitizes', () => {
    assert.deepEqual(plain(Roots.getPrefs()), { showGlobal: true, topFolder: 'global' });
    assert.equal(Roots.setPrefs({ showGlobal: false, topFolder: 'project' }), true);
    assert.deepEqual(rootIds(Roots.planRoots(RESOLVED)), ['workdir']);
    assert.equal(Roots.setPrefs({ showGlobal: false, topFolder: 'project' }), false, 'same choice is not a change');
    assert.equal(Roots.setPrefs({ showGlobal: 'no', topFolder: 'sideways' }), true);
    assert.deepEqual(plain(Roots.getPrefs()), { showGlobal: true, topFolder: 'global' }, 'junk falls back to the defaults');
    assert.deepEqual(rootIds(Roots.planRoots(RESOLVED)), ['user', 'workdir']);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
