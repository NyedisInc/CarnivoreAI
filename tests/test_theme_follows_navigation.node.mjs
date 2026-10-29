// the home screen
// and the real
// Exits 0 and prints ALL PASS on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

let failures = 0;
let passes = 0;

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

function readClientJs(relative) {
    return fs.readFileSync(path.join(ROOT, 'client', 'js', relative), 'utf8');
}

function makeEl() {
    const classes = new Set();
    return {
        classes,
        hidden: false,
        textContent: '',
        innerHTML: '',
        dataset: {},
        style: { setProperty() {}, removeProperty() {} },
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
            toggle(c, on) { if (on) classes.add(c); else classes.delete(c); },
        },
        setAttribute() {},
        getAttribute() { return null; },
        removeAttribute() {},
        appendChild() {},
        removeChild() {},
        addEventListener() {},
        removeEventListener() {},
        querySelector() { return null; },
        querySelectorAll() { return []; },
    };
}

function loadApp(opts) {
    const o = opts || {};
    const calls = {
        // the whole file
        applied: [],
        appliedOpts: [],
        scopes: [],
        terminalScopes: [],
        clearSession: 0,
    };

    const els = {};
    function el(id) {
        if (!els[id]) els[id] = makeEl();
        return els[id];
    }

    const docEl = makeEl();
    const doc = {
        title: '',
        body: makeEl(),
        documentElement: docEl,
        getElementById(id) { return el(id); },
        querySelector(sel) { return el('sel:' + sel); },
        querySelectorAll() { return []; },
        createElement() { return makeEl(); },
        addEventListener() {},
    };

    const store = new Map();
    store.set('cloude.theme', o.storedTheme === undefined ? 'claude' : o.storedTheme);

    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: doc,
        localStorage: {
            getItem(k) { return store.has(k) ? store.get(k) : null; },
            setItem(k, v) { store.set(k, String(v)); },
            removeItem(k) { store.delete(k); },
        },
        setTimeout: () => 0,
        setInterval: () => 0,
        clearInterval() {},
        clearTimeout() {},
        addEventListener() {},
        location: { pathname: '/' },
        history: { pushState() {}, replaceState() {} },
        fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);

    const known = new Set(['claude', 'matrix', 'terminal', 'nord']);
    sandbox.Themes = {
        DEFAULT_THEME_ID: 'claude',
        STORAGE_KEY: 'cloude.theme',
        getStoredThemeId() {
            const v = store.get('cloude.theme');
            return v || 'claude';
        },
        clearSession() { calls.clearSession++; },
        setActiveSession(n) { calls.scopes.push(n); },
        applyTheme(id, opt) {
            if (!known.has(id)) return false;
            calls.applied.push(id);
            calls.appliedOpts.push(opt || {});
            return true;
        },
        applySessionScope(ctx) { calls.terminalScopes.push(ctx || {}); },
    };
    vm.runInContext(readClientJs('theme-navigation.js'), sandbox);
    vm.runInContext(readClientJs('app-screen-entry.js'), sandbox);
    vm.runInContext(readClientJs('app.js'), sandbox);

    const app = sandbox.App;

    sandbox.ScreenChrome = { apply() {} };
    sandbox.TerminalController = {
        term: {},
        pauseForHome() {},
        connectToSession: () => Promise.resolve(),
        reconnectToExistingSession: () => Promise.resolve(),
    };
    sandbox.SessionSidebar = {
        hide() {}, show() {}, setActiveSession() {},
    };
    sandbox.Router = { resetToLauncher() {} };
    sandbox.Launchpad = {
        render: () => Promise.resolve(),
        show: () => Promise.resolve(),
        init: () => Promise.resolve(),
        loadProjects: () => Promise.resolve(),
        renderLaunchpadUI() {},
    };
    sandbox.DPad = { floatingButton: {}, init() {}, show() {}, hide() {} };
    sandbox.SlashCommandsModal = {
        button: {}, init: () => Promise.resolve(), hide() {}, show() {},
    };

    app.logoutBtn = makeEl();
    app.settingsBtn = makeEl();
    app.configEditorBtn = makeEl();
    app._placeStatusLight = () => {};
    app._syncSessionUrl = () => {};
    app._consumeStashedArchiveRoute = () => false;
    app.currentScreen = 'launchpad';

    return { app, calls, ctx: sandbox };
}

/* sit on the WRAPPER; */
function sessionInfo(name, pin, id) {
    return {
        tmux_session: name,
        pinned_theme: pin,
        agent_type: null,
        label: name,
        session: { id: id || name, working_dir: '/tmp', pty_pid: 1 },
    };
}

function settleIgnoringTail(promise) {
    if (promise && typeof promise.catch === 'function') promise.catch(() => {});
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('session to session: an UNPINNED target does not inherit the previous pin', () => {
    const { app, calls } = loadApp({ storedTheme: 'claude' });

    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_a', 'matrix')));
    assert.equal(calls.terminalScopes[calls.terminalScopes.length - 1].pinnedTheme,
        'matrix', 'entering a session with a pin must paint that pin on the '
        + 'session\'s own container');
    assert.equal(calls.applied[calls.applied.length - 1], 'claude',
        'and must NOT paint it on the page - the header and the '
        + 'conversations pane keep the home-page theme (issue #318)');

    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_b', null)));

    assert.equal(calls.terminalScopes[calls.terminalScopes.length - 1].pinnedTheme,
        null,
        'switching into an unpinned session must drop the previous '
        + 'session\'s pin off the terminal. Before the 2026-09-07 fix this '
        + 'branch applied NOTHING, so the last painted theme was still '
        + '"matrix" and the assertion failed here.');
    assert.equal(calls.applied[calls.applied.length - 1], 'claude',
        'and the page is the user\'s own global theme throughout');
});

test('session to session: the pin scope follows the target session', () => {
    const { app, calls } = loadApp({});
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_a', 'matrix')));
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_b', null)));

    assert.equal(calls.scopes[calls.scopes.length - 1], 'cloude_b');
});

test('the unpinned restore honours the user\'s OWN theme, not a hardcoded default', () => {
    const { app, calls } = loadApp({ storedTheme: 'nord' });
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_a', 'matrix')));
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_b', null)));
    assert.equal(calls.applied[calls.applied.length - 1], 'nord',
        'the page is whatever the user chose globally, read through '
        + 'Themes.getStoredThemeId()');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('showTerminal: an unpinned session also restores the global theme', () => {
    const { app, calls } = loadApp({ storedTheme: 'claude' });
    settleIgnoringTail(app.showTerminal(sessionInfo('cloude_a', 'terminal')));
    assert.equal(calls.terminalScopes[calls.terminalScopes.length - 1].pinnedTheme,
        'terminal');
    settleIgnoringTail(app.showTerminal(sessionInfo('cloude_b', null)));
    assert.equal(calls.terminalScopes[calls.terminalScopes.length - 1].pinnedTheme,
        null);
    assert.deepEqual([...new Set(calls.applied)], ['claude'],
        'both entries paint the page with the global theme and nothing else');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('going home from a pinned session still restores the global theme', () => {
    const { app, calls } = loadApp({ storedTheme: 'claude' });
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_a', 'matrix')));
    app.showLaunchpad();
    assert.equal(calls.applied[calls.applied.length - 1], 'claude');
    assert.equal(calls.scopes[calls.scopes.length - 1], null,
        'the home screen is not a session, so nothing may hold pin scope');
    assert.ok(calls.clearSession > 0,
        'leaving the terminal must drop the per-agent session scope too');
});

test('entering a session WITH a pin paints the TERMINAL, never the page', () => {
    const { app, calls } = loadApp({});
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_a', 'matrix')));
    const opts = calls.appliedOpts[calls.appliedOpts.length - 1];
    assert.equal(calls.applied[calls.applied.length - 1], 'claude',
        'the page keeps the home-page theme while a pinned session is open');
    assert.equal(opts.forXterm, false,
        'the page paint must not fire xterm; the terminal writer below does');
    const scope = calls.terminalScopes[calls.terminalScopes.length - 1];
    assert.ok(scope, 'entering a session must paint the terminal exactly once');
    assert.equal(scope.pinnedTheme, 'matrix',
        'the freshly attached session must repaint the terminal palette, '
        + 'not only the page chrome');
    assert.equal(opts.persist, false,
        'this is a repaint of a choice already made; the server owns the '
        + 'pin and the shared preference owns the global default');
});

test('the agent is NOT a theme rung: an unpinned terminal follows the page', () => {
    const { app, calls } = loadApp({ storedTheme: 'nord' });
    const pinned = sessionInfo('cloude_a', 'matrix');
    pinned.agent_type = 'claude';
    settleIgnoringTail(app.returnToExistingTerminal(pinned));
    const pinnedScope = calls.terminalScopes[calls.terminalScopes.length - 1];
    assert.equal(calls.terminalScopes.length, 1,
        'the terminal must be painted in ONE call; two calls is how the '
        + 'agent came to overwrite the pin');
    assert.equal(pinnedScope.pinnedTheme, 'matrix');

    const unpinned = sessionInfo('cloude_b', null);
    unpinned.agent_type = 'claude';
    settleIgnoringTail(app.returnToExistingTerminal(unpinned));
    const unpinnedScope = calls.terminalScopes[calls.terminalScopes.length - 1];
    assert.equal(unpinnedScope.pinnedTheme, null,
        'an unpinned session carries no pin into the terminal');
    assert.equal(unpinnedScope.agentType, undefined,
        'and carries no agent either - the agent is not an input any more');
    assert.equal(calls.applied[calls.applied.length - 1], 'nord',
        'the page, and therefore the unpinned terminal under it, is the '
        + 'user\'s global theme');
});

test('a pin naming an uninstalled theme is refused by ONE owner, the registry', () => {
    const { app, calls } = loadApp({});
    const info = sessionInfo('cloude_a', 'uninstalled-theme');
    info.agent_type = 'claude';
    settleIgnoringTail(app.returnToExistingTerminal(info));
    assert.equal(calls.applied[calls.applied.length - 1], 'claude',
        'the page is the global theme, as it is for every navigation');
    const refusedScope = calls.terminalScopes[calls.terminalScopes.length - 1];
    assert.equal(refusedScope.pinnedTheme, 'uninstalled-theme',
        'the pin reaches the registry verbatim; the registry, not this '
        + 'module, decides whether it names anything installed');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('an ADOPTED session takes theme scope by tmux name, never by its id', () => {
    const { app, calls } = loadApp({});
    settleIgnoringTail(app.returnToExistingTerminal(
        sessionInfo('legacy_pane', 'matrix', 'adopted:legacy_pane')));
    assert.equal(calls.scopes[calls.scopes.length - 1], 'legacy_pane');
    assert.ok(!String(calls.scopes[calls.scopes.length - 1]).startsWith('adopted:'));
});

test('a pin on the nested .session is still found (wrapper vs inner levels)', () => {
    const { app, calls } = loadApp({});
    settleIgnoringTail(app.returnToExistingTerminal({
        session: { id: 'cloude_c', name: 'cloude_c', pinned_theme: 'matrix' },
    }));
    assert.equal(calls.terminalScopes[calls.terminalScopes.length - 1].pinnedTheme,
        'matrix');
});

test('a pin naming an UNINSTALLED theme falls back instead of keeping the stale one', () => {
    const { app, calls } = loadApp({ storedTheme: 'claude' });
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_a', 'matrix')));
    settleIgnoringTail(app.returnToExistingTerminal(sessionInfo('cloude_b', 'deleted-theme')));
    assert.equal(calls.applied[calls.applied.length - 1], 'claude');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('no navigation path in app.js hand-rolls the theme restore', () => {
    const src = readClientJs('app.js');
    assert.ok(!/localStorage\.getItem\(\s*'cloude\.theme'\s*\)/.test(src),
        'app.js must not re-derive the global theme id; that lives in '
        + 'Themes.getStoredThemeId(), reached through ThemeNavigation. Three '
        + 'hand-copied versions of that read are what let the '
        + 'session-to-session path ship with no restore at all.');
    assert.ok(!/Themes\.applyTheme\(/.test(src),
        'app.js must route every paint through ThemeNavigation so a new '
        + 'navigation path cannot reintroduce a branch that paints nothing.');
});

test('index.html loads theme-navigation.js after the registry and before app.js', () => {
    const html = fs.readFileSync(path.join(ROOT, 'client', 'index.html'), 'utf8');
    const order = [...html.matchAll(/<script\s+src="\/static\/js\/([^"]+)"/g)]
        .map((m) => m[1]);
    const at = (name) => order.indexOf(name);
    assert.ok(at('theme-navigation.js') >= 0,
        'theme-navigation.js is not loaded by index.html at all');
    assert.ok(at('themes/registry.js') >= 0 && at('app.js') >= 0,
        'positive control: the script extractor found neither the registry '
        + 'nor app.js, so this test could assert nothing');
    assert.ok(at('themes/registry.js') < at('theme-navigation.js'),
        'theme-navigation.js calls window.Themes, so the registry loads first');
    assert.ok(at('theme-navigation.js') < at('app.js'),
        'every app.js navigation calls window.ThemeNavigation');
});

test('every navigation target resolves to a painted theme (the function is total)', () => {
    const { ctx } = loadApp({ storedTheme: 'claude' });
    const TN = ctx.ThemeNavigation;
    assert.equal(TN.applyForTarget({ kind: 'session', sessionName: 'a', pinnedTheme: 'matrix' }), 'claude');
    assert.equal(TN.applyForTarget({ kind: 'session', sessionName: 'a', pinnedTheme: null }), 'claude');
    assert.equal(TN.applyForTarget({ kind: 'global' }), 'claude');
});

test('a global theme change repaints the CURRENT target without a navigation', () => {
    const { ctx, calls } = loadApp({ storedTheme: 'claude' });
    const TN = ctx.ThemeNavigation;
    TN.applyForTarget({ kind: 'session', sessionName: 'a', pinnedTheme: 'matrix' });

    ctx.localStorage.setItem('cloude.theme', 'nord');
    assert.equal(TN.reapply(), 'nord',
        'the page takes the new global default with no navigation');
    const scope = calls.terminalScopes[calls.terminalScopes.length - 1];
    assert.equal(scope.pinnedTheme, 'matrix',
        'THE OWNER\'S EXCEPTION HOLDS THROUGH A LIVE CHANGE: the pinned '
        + 'session does not move. MUTATION THAT MUST TURN THIS RED: make '
        + 'reapply() replay a captured theme id, or repaint the page only.');
});

test('the global-theme follower is loaded, and after the modules it calls', () => {
    const html = fs.readFileSync(path.join(ROOT, 'client', 'index.html'), 'utf8');
    const order = [...html.matchAll(/<script\s+src="\/static\/js\/([^"]+)"/g)]
        .map((m) => m[1]);
    const at = (name) => order.indexOf(name);
    assert.ok(at('theme-global-follow.js') >= 0,
        'theme-global-follow.js is not loaded by index.html at all');
    assert.ok(at('preference-bridge.js') >= 0,
        'positive control: the extractor found no preference bridge, so '
        + 'this test could assert nothing about ordering');
    assert.ok(at('preference-bridge.js') < at('theme-global-follow.js'),
        'the follower subscribes through PreferenceBridge');
    assert.ok(at('theme-navigation.js') < at('theme-global-follow.js'),
        'the follower calls ThemeNavigation.reapply()');
});

console.log('');
if (failures) {
    console.error(`${failures} FAILED, ${passes} passed`);
    process.exit(1);
}
console.log(`ALL PASS - ${passes} assertions`);
