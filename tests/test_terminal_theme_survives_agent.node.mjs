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

const queued = [];

function test(name, fn) {
    queued.push({ name, fn });
}

async function run() {
    for (const { name, fn } of queued) {
        try {
            await fn();
            passes++;
            console.log(`ok - ${name}`);
        } catch (err) {
            failures++;
            console.error(`NOT OK - ${name}`);
            console.error(err && err.stack ? err.stack : err);
        }
    }
}

function manifest(id) {
    const m = JSON.parse(fs.readFileSync(
        path.join(ROOT, 'client', 'css', 'themes', id, 'theme.json'), 'utf8'));
    m.source = 'builtin';
    return m;
}

const DRACULA = manifest('dracula');
const CLAUDE = manifest('claude');
const MATRIX = manifest('matrix');

function makeEl() {
    const classes = new Set();
    const inline = new Map();
    return {
        inline,
        dataset: {},
        hidden: false,
        textContent: '',
        innerHTML: '',
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
            toggle(c, on) { if (on) classes.add(c); else classes.delete(c); },
        },
        style: {
            setProperty(k, v) { inline.set(k, v); },
            removeProperty(k) { inline.delete(k); },
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

function boot(opts) {
    const o = opts || {};
    const rows = o.themes || [CLAUDE, DRACULA, MATRIX];

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
    store.set('carnivore.theme', o.storedTheme === undefined ? 'claude' : o.storedTheme);
    const allowlist = {};
    rows.forEach((m) => { allowlist[m.id] = false; });
    store.set('cloude.themeJsAllowlist', JSON.stringify(allowlist));

    const patched = [];
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
        clearTimeout() {},
        clearInterval() {},
        addEventListener() {},
        location: { pathname: '/' },
        history: { pushState() {}, replaceState() {} },
        Set, Map, Object, Array, JSON, Promise, Error, String, Number,
        Boolean, RegExp,
        fetch(url, init) {
            if (String(url).indexOf('/api/v1/themes') === 0) {
                return Promise.resolve({
                    ok: true, status: 200,
                    json: () => Promise.resolve(rows),
                });
            }
            patched.push({ url: String(url), body: init && init.body });
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
        },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);

    const load = (rel) => vm.runInContext(
        fs.readFileSync(path.join(ROOT, 'client', 'js', rel), 'utf8'),
        sandbox, { filename: rel });
    load('theme-var-writer.js');
    load('themes/registry.js');
    load('theme-navigation.js');
    load('app-screen-entry.js');
    load('app.js');

    sandbox.ScreenChrome = { apply() {} };
    sandbox.TerminalController = {
        term: {},
        pauseForHome() {},
        connectToSession: () => Promise.resolve(),
        reconnectToExistingSession: () => Promise.resolve(),
    };
    sandbox.SessionSidebar = { hide() {}, show() {}, setActiveSession() {} };
    sandbox.Router = { resetToLauncher() {} };
    sandbox.Launchpad = {
        render: () => Promise.resolve(), show: () => Promise.resolve(),
        init: () => Promise.resolve(), loadProjects: () => Promise.resolve(),
        renderLaunchpadUI() {},
    };
    sandbox.DPad = { floatingButton: {}, init() {}, show() {}, hide() {} };
    sandbox.SlashCommandsModal = {
        button: {}, init: () => Promise.resolve(), hide() {}, show() {},
    };

    const app = sandbox.App;
    app.logoutBtn = makeEl();
    app.settingsBtn = makeEl();
    app.configEditorBtn = makeEl();
    app._placeStatusLight = () => {};
    app._syncSessionUrl = () => {};
    app._consumeStashedArchiveRoute = () => false;
    app.currentScreen = 'launchpad';

    const fired = [];
    sandbox.Themes.onXtermThemeChange((p) => fired.push(p));

    return {
        app,
        Themes: sandbox.Themes,
        ThemeNavigation: sandbox.ThemeNavigation,
        fired,
        patched,
        docEl,
        scope: el('terminal-container'),
        screen: el('terminal-screen'),
        lastPalette: () => fired[fired.length - 1] || {},
    };
}

/* sit on the WRAPPER; sits on the nested */
function sessionInfo(name, pin, agent, id) {
    return {
        tmux_session: name,
        pinned_theme: pin,
        agent_type: agent === undefined ? null : agent,
        label: name,
        session: { id: id || name, working_dir: '/tmp', pty_pid: 1 },
    };
}

function swallow(promise) {
    if (promise && typeof promise.catch === 'function') promise.catch(() => {});
}

function assertPalette(actual, expected, what) {
    Object.keys(expected).forEach((k) => {
        assert.equal(actual[k], expected[k],
            `${what}: xterm.${k} should be ${expected[k]}, got ${actual[k]}`);
    });
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('a dracula-pinned session keeps its terminal palette across leave and return', async () => {
    const t = boot({});
    await t.Themes.init();
    const info = sessionInfo('cloude_dracula', 'dracula', 'claude');

    swallow(t.app.showTerminal(info, {}));
    t.Themes.applyGlobal('dracula');
    assertPalette(t.lastPalette(), DRACULA.xterm, 'immediately after the pick');
    assert.equal(t.scope.dataset.sessionTheme, 'dracula',
        'the pick must move the terminal CSS scope too, not only the palette');

    t.app.showLaunchpad();
    swallow(t.app.returnToExistingTerminal(info));

    assertPalette(t.lastPalette(), DRACULA.xterm,
        'after leaving and returning - this is the reported defect');
    assert.equal(t.docEl.dataset.theme, 'claude',
        'THE PAGE NEVER FOLLOWS A PIN (issue #318). MUTATION THAT MUST TURN '
        + 'THIS RED: let applyGlobal() or applyForTarget() paint the pin on '
        + ':root again, which is what turned the top bar and the '
        + 'conversations pane dracula along with one terminal.');
    assert.equal(t.scope.dataset.sessionTheme, 'dracula',
        'nothing may take the terminal scope back on re-entry');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('an UNPINNED session wears the global theme, not its agent', async () => {
    const t = boot({ storedTheme: 'dracula' });
    await t.Themes.init();
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', null, 'claude')));
    assertPalette(t.lastPalette(), DRACULA.xterm,
        'an unpinned session follows the home-page theme');
    assert.equal(t.docEl.dataset.theme, 'dracula',
        'and so does the page - one theme, two surfaces, no split');
    assert.equal(t.scope.dataset.sessionTheme, undefined,
        'no session scope is claimed when there is nothing to scope');
});

test('a null agent and a named agent both hand the terminal to the global theme', async () => {
    for (const agent of [null, 'claude', 'no-such-agent-1234']) {
        const t = boot({ storedTheme: 'dracula' });
        await t.Themes.init();
        swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', null, agent)));
        assertPalette(t.lastPalette(), DRACULA.xterm,
            `agent ${String(agent)} is not a rung, so the global theme governs`);
        assert.equal(t.scope.dataset.sessionTheme, undefined,
            'no session scope may be left on the session container');
        assert.equal(t.scope.inline.size, 0,
            'and no scoped CSS variable may be left behind either');
    }
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('A/B/A: dracula -> a differently themed session -> dracula', async () => {
    const t = boot({});
    await t.Themes.init();
    const a = sessionInfo('cloude_a', 'dracula', 'claude');
    const b = sessionInfo('cloude_b', 'matrix', 'claude');

    swallow(t.app.returnToExistingTerminal(a));
    assertPalette(t.lastPalette(), DRACULA.xterm, 'A');
    swallow(t.app.returnToExistingTerminal(b));
    assertPalette(t.lastPalette(), MATRIX.xterm, 'B');
    swallow(t.app.returnToExistingTerminal(a));
    assertPalette(t.lastPalette(), DRACULA.xterm, 'back to A');
    assert.equal(t.scope.dataset.sessionTheme, 'dracula');
});

test('no scoped CSS variable from the previous owner survives a switch', async () => {
    const t = boot({});
    await t.Themes.init();
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', 'matrix', 'claude')));
    const matrixOnly = Object.keys(MATRIX.cssVars || {})
        .filter((k) => !(DRACULA.cssVars || {})[k]);
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_b', 'dracula', 'claude')));

    matrixOnly.forEach((k) => {
        assert.equal(t.scope.inline.has(k), false,
            `${k} belongs to the outgoing theme and must be removed, not orphaned`);
    });
    Object.keys(DRACULA.cssVars || {}).forEach((k) => {
        assert.equal(t.scope.inline.get(k), DRACULA.cssVars[k],
            `${k} must carry the incoming theme's value`);
    });
});

test('first attach: a terminal built AFTER the paint seeds from the session theme', async () => {
    const t = boot({});
    await t.Themes.init();
    swallow(t.app.showTerminal(sessionInfo('cloude_a', 'dracula', 'claude'), {}));
    assertPalette(t.Themes.getActiveTerminalManifest().xterm, DRACULA.xterm,
        'the seed a freshly constructed xterm would read');
    assert.equal(t.Themes.getActiveGlobal().id, 'claude',
        'while the page keeps the user global theme - the two DISAGREE here, '
        + 'which is precisely why seeding from getActiveGlobal() was wrong, '
        + 'and is the owner\'s "one screen, two themes" requirement');
});

test('an unpinned first attach seeds from the PAGE, since nothing overrides it', async () => {
    const t = boot({ storedTheme: 'dracula' });
    await t.Themes.init();
    swallow(t.app.showTerminal(sessionInfo('cloude_a', null, 'claude'), {}));
    assertPalette(t.Themes.getActiveTerminalManifest().xterm, DRACULA.xterm,
        'the terminal seed follows the global theme');
    assert.equal(t.Themes.getActiveGlobal().id, 'dracula');
});

test('going home drops the session scope, and returning restores the pin', async () => {
    const t = boot({});
    await t.Themes.init();
    const info = sessionInfo('cloude_a', 'dracula', 'claude');
    swallow(t.app.returnToExistingTerminal(info));
    t.app.showLaunchpad();
    assertPalette(t.lastPalette(), CLAUDE.xterm,
        'the launchpad is not a session, so the global theme governs xterm');
    assert.equal(t.scope.dataset.sessionTheme, undefined);
    assert.equal(t.scope.inline.size, 0);

    swallow(t.app.returnToExistingTerminal(info));
    assertPalette(t.lastPalette(), DRACULA.xterm, 'and the pin comes back');
});

test('PIN REMOVAL: a session whose pin is gone falls back to the page', async () => {
    const t = boot({});
    await t.Themes.init();
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', 'dracula', 'claude')));
    assertPalette(t.lastPalette(), DRACULA.xterm, 'pinned');

    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', null, 'claude')));
    assertPalette(t.lastPalette(), CLAUDE.xterm,
        'removing the pin must release the terminal to the page theme, not '
        + 'strand it on the theme that was pinned a moment ago');
    assert.equal(t.scope.dataset.sessionTheme, undefined,
        'and must drop the scope rather than re-claim it for the agent');
});

test('a pin naming an UNAVAILABLE theme falls back without stranding the terminal', async () => {
    const t = boot({});
    await t.Themes.init();
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', 'dracula', 'claude')));
    swallow(t.app.returnToExistingTerminal(
        sessionInfo('cloude_b', 'uninstalled-theme', 'claude')));
    assert.equal(t.docEl.dataset.theme, 'claude');
    assertPalette(t.lastPalette(), CLAUDE.xterm,
        'an unknown pin must not leave the previous session\'s palette up');
});

test('RAPID SWITCHING: the last navigation wins, every time', async () => {
    const t = boot({});
    await t.Themes.init();
    const order = ['dracula', 'matrix', 'dracula', 'matrix', 'dracula'];
    order.forEach((id, i) => {
        swallow(t.app.returnToExistingTerminal(
            sessionInfo('cloude_' + i, id, 'claude')));
    });
    assertPalette(t.lastPalette(), DRACULA.xterm, 'the last target');
    assert.equal(t.scope.dataset.sessionTheme, 'dracula');
});

test('a PICKER CHANGE is durable: it survives leaving and returning', async () => {
    const t = boot({});
    await t.Themes.init();
    const info = sessionInfo('cloude_a', null, 'claude');
    swallow(t.app.returnToExistingTerminal(info));
    assertPalette(t.lastPalette(), CLAUDE.xterm, 'unpinned, so the page theme');

    t.Themes.applyGlobal('dracula');
    assertPalette(t.lastPalette(), DRACULA.xterm, 'the pick takes effect at once');
    assert.equal(t.scope.dataset.sessionTheme, 'dracula',
        'and it moves the CSS scope, not just the palette');
    assert.equal(t.docEl.dataset.theme, 'claude',
        'A PICK INSIDE A SESSION IS A PIN AND ONLY A PIN. MUTATION THAT '
        + 'MUST TURN THIS RED: let applyGlobal() paint :root while a '
        + 'session is in scope.');
    assert.ok(t.patched.some((p) => p.url.indexOf('cloude_a') >= 0),
        'the pick must be PATCHed against the tmux name so the server can '
        + 'report it as the pin on the next visit');

    t.app.showLaunchpad();
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', 'dracula', 'claude')));
    assertPalette(t.lastPalette(), DRACULA.xterm,
        'leaving and returning must not undo a saved choice');
});

test('a picker change mid-replay is not undone by the replay finishing', async () => {
    const t = boot({});
    await t.Themes.init();
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_a', null, 'claude')));

    t.Themes.setReplayInProgress(true);
    swallow(t.app.returnToExistingTerminal(sessionInfo('cloude_b', null, 'claude')));
    t.Themes.applyGlobal('dracula');
    t.Themes.setReplayInProgress(false);

    assertPalette(t.lastPalette(), DRACULA.xterm,
        'the deferred paint must re-resolve on drain; replaying the id it '
        + 'was deferred with would repaint the theme the user just left');
    assert.equal(t.scope.dataset.sessionTheme, 'dracula');
});

test('RECONNECT: re-entering the same session repeatedly is idempotent', async () => {
    const t = boot({});
    await t.Themes.init();
    const info = sessionInfo('cloude_a', 'dracula', 'claude');
    for (let i = 0; i < 3; i++) {
        swallow(t.app.returnToExistingTerminal(info));
        assertPalette(t.lastPalette(), DRACULA.xterm, `re-entry ${i + 1}`);
    }
    Object.keys(DRACULA.cssVars || {}).forEach((k) => {
        assert.equal(t.scope.inline.get(k), DRACULA.cssVars[k]);
    });
    assert.equal(t.scope.inline.size, Object.keys(DRACULA.cssVars || {}).length,
        'repeated entry must not accumulate variables');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
test('the resolution is the pin or nothing, and nothing else', async () => {
    const t = boot({ storedTheme: 'matrix' });
    await t.Themes.init();

    t.Themes.applySessionScope({ pinnedTheme: 'dracula' });
    assert.equal(t.Themes.resolveTerminalThemeId(), 'dracula', 'pin wins');

    t.Themes.applySessionScope({ pinnedTheme: null, agentType: 'claude' });
    assert.equal(t.Themes.resolveTerminalThemeId(), null,
        'an agent is not a rung; the global theme governs');

    t.Themes.applySessionScope({ pinnedTheme: null });
    assert.equal(t.Themes.resolveTerminalThemeId(), null,
        'with no pin, the global theme governs and there is no session theme');

    t.Themes.applySessionScope({ pinnedTheme: 'nope' });
    assert.equal(t.Themes.resolveTerminalThemeId(), null,
        'a pin naming a theme that is not installed is not a choice');
});

test('TWO SESSIONS, TWO PINS, ONE SCREEN: each cell resolves on its own', async () => {
    const t = boot({ storedTheme: 'matrix' });
    await t.Themes.init();
    t.Themes.applySessionScope({ pinnedTheme: 'dracula' });

    assert.equal(t.Themes.getSessionManifest({ pinnedTheme: 'claude' }).id, 'claude',
        'a cell pinned to claude paints claude while the page pane is dracula');
    assert.equal(t.Themes.getSessionManifest({ pinnedTheme: null }).id, 'matrix',
        'and an unpinned cell paints the home-page theme, not the page pane\'s pin');
    assert.equal(t.Themes.resolveTerminalThemeId(), 'dracula',
        'positive control: the page pane really is in dracula scope, so a cell '
        + 'answering something else is answering from its own input');
});

test('applyScopeTo paints ONE element and releases everything it wrote', async () => {
    const t = boot({ storedTheme: 'matrix' });
    await t.Themes.init();
    t.Themes.applySessionScope({ pinnedTheme: 'dracula' });

    const panel = { inline: new Map(), dataset: {}, style: null };
    panel.style = {
        setProperty(k, v) { panel.inline.set(k, v); },
        removeProperty(k) { panel.inline.delete(k); },
    };

    const release = t.Themes.applyScopeTo(panel, { pinnedTheme: 'claude' });
    assert.equal(panel.dataset.sessionTheme, 'claude',
        'the panel wears the theme of the session whose data it shows');
    assert.ok(panel.inline.size > 0, 'and its variables are actually written');
    assert.equal(t.Themes.resolveTerminalThemeId(), 'dracula',
        'positive control: the page pane is still dracula, so the panel '
        + 'answered from its own input');
    assert.notEqual(t.docEl.dataset.theme, 'claude',
        'and the PAGE never moved - a panel is a subtree, not the document');

    release();
    assert.equal(panel.inline.size, 0, 'release removes every variable it wrote');
    assert.equal(panel.dataset.sessionTheme, undefined, 'and drops the scope');
});

test('an UNPINNED session panel wears the global theme, not nothing', async () => {
    const t = boot({ storedTheme: 'matrix' });
    await t.Themes.init();
    const panel = { inline: new Map(), dataset: {}, style: null };
    panel.style = {
        setProperty(k, v) { panel.inline.set(k, v); },
        removeProperty(k) { panel.inline.delete(k); },
    };
    const release = t.Themes.applyScopeTo(panel, { pinnedTheme: null });
    assert.equal(panel.dataset.sessionTheme, 'matrix',
        'a panel for a session nobody themed follows the home page');
    release();
});

await run();

if (failures > 0) {
    console.error(`\n${failures} FAILED, ${passes} passed`);
    process.exit(1);
}
console.log(`\nALL PASS - ${passes} assertions`);
