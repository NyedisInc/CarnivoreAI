
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createEnvironment } from './mini-dom.mjs';
import CATALOG from '../client/js/i18n/catalog.en.js';
import { headerActionLabels, HEADER_ACTION_KEYS } from '../client/js/labels/header-actions.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

const EXPECTED_IDS = [
    'logoutBtn',
    'settingsBtn',
];

const CONTROL_IDS = EXPECTED_IDS.concat(['headerMasterAllBtn']);

/* the drawer toggle */
const TOOL_IDS = [
    'configEditorBtn', 'sessionNotesBtn',
];

const REMOVED_IDS = ['homeBtn', 'detachSessionBtn', 'audioToggleBtn', 'sessionEditorBtn'];

const SESSION_ROW_IDS = ['headerSessionThemeBtn', 'headerDetachBtn', 'headerSizeMasterBtn',
    'headerComponentsBtn'];

const FOLD_ORDER = SESSION_ROW_IDS.concat(TOOL_IDS, CONTROL_IDS);

function buildHeader(document) {
    const header = document.createElement('div');
    header.className = 'header';
    const controls = document.createElement('div');
    controls.className = 'controls';
    for (const id of EXPECTED_IDS.concat(TOOL_IDS)) {
        const btn = document.createElement('button');
        btn.setAttribute('type', 'button');
        btn.setAttribute('id', id);
        btn.setAttribute('title', id.toLowerCase());
        controls.appendChild(btn);
    }
    const status = document.createElement('span');
    status.className = 'status';
    status.setAttribute('id', 'statusText');
    controls.appendChild(status);
    header.appendChild(controls);
    document.body.appendChild(header);
    return { controls, status };
}

/* and the real no string layer */
function load(options = {}) {
    const mobile = options.mobile !== undefined ? !!options.mobile : true;
    const env = createEnvironment({ matches: mobile });
    const built = buildHeader(env.document);
    const sandbox = {
        window: env.window,
        document: env.document,
        console: { log() {}, warn() {}, error() {} },
    };
    sandbox.globalThis = sandbox;
    if (options.i18n) {
        sandbox.CloudeI18n = { t: (key) => (key in CATALOG ? CATALOG[key] : key) };
        sandbox.CloudeLabels = { headerActionLabels };
    }
    vm.createContext(sandbox);
    for (const file of ['kebab-icon.js', 'dismiss-guard.js', 'header-menu.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(__dirname, '..', 'client', 'js', file), 'utf8'),
            sandbox);
    }
    return {
        env,
        menu: env.window.HeaderMenu,
        controls: built.controls,
        status: built.status,
        menuConstants: env.window.HeaderMenuConstants,
        setMediaMatches: env.setMediaMatches,
    };
}

function buttonIds(node) {
    return node.children
        .filter(c => c.tagName === 'BUTTON' && c.getAttribute('id') !== 'header-menu-toggle')
        .map(c => c.getAttribute('id'));
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the module and index.html agree on which controls the menu owns', () => {
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'header-menu.js'), 'utf8');
    for (const id of EXPECTED_IDS) {
        assert.ok(src.includes(`'${id}'`), `header-menu.js forgot ${id}`);
        assert.ok(html.includes(`id="${id}"`), `index.html has no ${id}`);
    }
    assert.deepEqual(
        JSON.parse(JSON.stringify(load().menuConstants.CONTROL_IDS)),
        CONTROL_IDS, 'the exported list is the contract');
});

test('THE OVERFLOW HOLDS EXACTLY search, session theme, detach, components, logout and settings', () => {
    const { env, controls } = load();
    const panel = env.document.getElementById('header-menu-panel');
    assert.deepEqual(buttonIds(panel), FOLD_ORDER);
    assert.deepEqual(buttonIds(controls), [],
        'below the fold width nothing but the trigger may stay inline');
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'header-menu.js'), 'utf8');
    assert.ok(!/HEADER_MENU_CONTROL_IDS\s*=\s*\[[^\]]*configEditorBtn/.test(src),
        'configEditorBtn is claimed by two lists; foldOrder() would name it twice');
});

test('HOME, THE OLD SESSION EDITOR BUTTON AND APP SOUND ARE GONE from the header, markup included', () => {
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    for (const id of REMOVED_IDS) {
        assert.ok(!html.includes(`id="${id}"`),
            `${id} must be deleted, not hidden - a hidden button is still `
            + 'a node every id lookup and fold list has to keep agreeing on');
    }
    const app = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'app.js'), 'utf8');
    assert.ok(!/getElementById\(['"]homeBtn['"]\)/.test(app),
        'app.js must not look up a button that no longer exists');
});

test('THE TITLE IS THE HOME CONTROL, and it calls goHome()', () => {
    const app = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'app.js'), 'utf8');
    const wire = app.slice(app.indexOf("const appTitle ="));
    assert.match(wire, /DismissGuard\.onContainerActivate\(appTitle/,
        'the title must stay behind the dismiss guard');
    assert.ok(!/appTitle\.addEventListener\(\s*['"]click['"]/.test(app),
        'a bare click listener on #appTitle is the rename-focus bug');
    const handler = wire.slice(0, wire.indexOf('});'));
    assert.match(handler, /this\.goHome\(\)/,
        'the title must call goHome(), not bare showLaunchpad()');
    assert.match(app, /goHome\(\)\s*\{[\s\S]*?pauseForHome\(\)/,
        'goHome must still pause the socket');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the kebab builds the screen rows, above logout and settings', () => {
    const { env } = load();
    const panel = env.document.getElementById('header-menu-panel');
    assert.deepEqual(buttonIds(panel), FOLD_ORDER,
        'the screen rows sit above the tools, and both above logout and settings');
});

test('session theme opens SessionThemeMenu, anchored to the kebab toggle', () => {
    const { env, menu } = load();
    const calls = [];
    env.window.SessionThemeMenu = { open: (anchor) => calls.push(anchor) };
    env.document.getElementById('headerSessionThemeBtn').dispatchEvent('click');
    assert.equal(calls.length, 1, 'SessionThemeMenu.open must be called once');
    assert.equal(calls[0], env.document.getElementById('header-menu-toggle'),
        'it must anchor to the kebab toggle, which stays on screen after '
        + 'the panel this row lives in collapses');
});

test('a missing SessionThemeMenu does not throw', () => {
    const { env } = load();
    delete env.window.SessionThemeMenu;
    env.document.getElementById('headerSessionThemeBtn').dispatchEvent('click');
});

test('detach calls TerminalController.detachSession(), the same method the deleted button called', () => {
    const { env } = load();
    let calls = 0;
    env.window.TerminalController = { detachSession: () => { calls++; } };
    env.document.getElementById('headerDetachBtn').dispatchEvent('click');
    assert.equal(calls, 1);
});

test('a missing TerminalController does not throw', () => {
    const { env } = load();
    delete env.window.TerminalController;
    env.document.getElementById('headerDetachBtn').dispatchEvent('click');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the header builds no search button and its catalog keys are gone', () => {
    const { env } = load({ i18n: true });
    assert.equal(env.document.getElementById('headerSearchBtn'), null);
    assert.equal(CATALOG['header.menu.search'], undefined);
    assert.equal(CATALOG['sessions_search.open'], undefined);
    const css = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'css', 'header-menu.css'), 'utf8');
    assert.doesNotMatch(css, /headerSearchBtn/);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the row reads "pause session", never "detach", while its id and wire stay put', () => {
    const { env } = load({ i18n: true });
    const btn = env.document.getElementById('headerDetachBtn');
    assert.equal(btn.getAttribute('title'), null);
    assert.equal(btn.getAttribute('data-tooltip'), null);
    const label = btn.getAttribute('aria-label');
    assert.ok(/^pause session\b/.test(label), `aria-label must open with "pause session": ${label}`);
    assert.ok(/resume later/.test(label), `aria-label must say the session can be resumed: ${label}`);
    assert.ok(!/detach/i.test(label), 'aria-label must not say "detach" any more');
    assert.equal(label, label.toLowerCase());
});

test('the pause copy comes from the catalog, not from header-menu.js', () => {
    const { env } = load();
    const btn = env.document.getElementById('headerDetachBtn');
    assert.equal(btn.getAttribute('title'), null);
    assert.equal(btn.getAttribute('data-tooltip'), null);
    assert.equal(btn.getAttribute('aria-label'), HEADER_ACTION_KEYS.pauseHint);
    const src = fs.readFileSync(path.join(__dirname, '..', 'client', 'js', 'header-menu.js'), 'utf8');
    assert.ok(!/'pause session/.test(src), 'no pause string literal in header-menu.js');
    assert.equal(CATALOG[HEADER_ACTION_KEYS.pause], 'pause session');
    assert.ok(/^pause session\b/.test(CATALOG[HEADER_ACTION_KEYS.pauseHint]));
});

test('the phone panel drops the struck qualifiers: theme, pause, notes (owner, 2026-09-22)', () => {
    const { env } = load({ i18n: true });
    const expected = {
        headerSessionThemeBtn: 'theme',
        headerDetachBtn: 'pause',
        sessionNotesBtn: 'notes',
    };
    const panel = env.document.getElementById('header-menu-panel');
    for (const [id, label] of Object.entries(expected)) {
        const el = env.document.getElementById(id);
        assert.equal(el.parentNode, panel, `${id} must be folded into the panel`);
        assert.equal(el.getAttribute('data-menu-label'), label, `${id} panel label`);
        assert.ok(!/session|browse|install/.test(label));
    }
    const pause = env.document.getElementById('headerDetachBtn');
    assert.equal(pause.getAttribute('title'), null);
    assert.ok(/resume later/.test(pause.getAttribute('aria-label')));
    const css = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'css', 'header-menu.css'), 'utf8');
    const rule = css.indexOf('.header-menu-panel button[data-menu-label]::after {');
    assert.ok(rule > css.indexOf('.header-menu-panel button[data-tooltip]::after,'),
        'the short-label rule must follow the title rule it overrides');
    assert.ok(/^[^}]*content:\s*attr\(data-menu-label\)/.test(css.slice(rule)));
});

test('the short panel labels come from the catalog, not header-menu.js', () => {
    const { env } = load();
    assert.equal(env.document.getElementById('headerDetachBtn')
        .getAttribute('data-menu-label'), 'header.menu.pause');
    assert.equal(CATALOG['header.menu.theme'], 'theme');
    assert.equal(CATALOG['header.menu.pause'], 'pause');
});

test('the row draws two bars, not the old box-and-arrow glyph', () => {
    const { env } = load();
    const svg = env.document.getElementById('headerDetachBtn').innerHTML;
    const shapes = svg.match(/<path\b[^>]*>/g) || [];
    assert.equal(shapes.length, 2, `pause must draw exactly two strokes: ${svg}`);
    for (const shape of shapes) {
        assert.ok(/stroke="currentColor"/.test(shape) && /stroke-width="1\.5"/.test(shape),
            `each bar must match the panel's icon contract: ${shape}`);
        assert.ok(/^<path d="M[\d.]+ 3\.5V12\.5"/.test(shape),
            `each bar must be a plain vertical line: ${shape}`);
    }
    assert.ok(!/L12\.5 3\.5/.test(svg), 'the old arrow stroke must not survive the rename');
});

test('picking a session row closes the menu behind it too', () => {
    const { env, menu } = load();
    env.window.SessionThemeMenu = { open: () => {} };
    env.document.getElementById('header-menu-toggle').dispatchEvent('click');
    assert.equal(menu.isOpen, true);
    env.document.getElementById('headerSessionThemeBtn').dispatchEvent('click');
    assert.equal(menu.isOpen, false);
});

test('the session rows carry an accessible name', () => {
    const { env } = load();
    for (const id of SESSION_ROW_IDS) {
        const el = env.document.getElementById(id);
        assert.ok(el.getAttribute('aria-label'), `${id} needs an accessible name`);
        assert.ok(el.getAttribute('title') || el.getAttribute('data-tooltip') || el.getAttribute('data-menu-label'),
            `${id} needs a visible row label`);
    }
});

test('the controls in the menu are the SAME nodes, not copies', () => {
    const { env } = load({ mobile: true });
    for (const id of EXPECTED_IDS) {
        const matches = env.document.querySelectorAll(`#${id}`);
        assert.equal(matches.length, 1, `${id} exists ${matches.length} times`);
    }
});

test('listeners survive the move', () => {
    const { env } = load({ mobile: true });
    const logout = env.document.getElementById('logoutBtn');
    let clicked = 0;
    logout.addEventListener('click', () => { clicked++; });
    logout.dispatchEvent('click');
    assert.equal(clicked, 1);
});

test('the status light is NOT folded away', () => {
    const { env, controls, status } = load({ mobile: true });
    const panel = env.document.getElementById('header-menu-panel');
    assert.ok(controls.contains(status), 'status must stay inline');
    assert.ok(!panel.contains(status));
});

test('the sidebar toggle is never touched', () => {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'header-menu.js'), 'utf8');
    assert.ok(!/CONTROL_IDS[\s\S]*session-sidebar-toggle/.test(src));
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('NARROW folds everything into the panel, WIDE unfolds it inline (#317)', () => {
    const narrow = load({ mobile: true });
    const narrowPanel = narrow.env.document.getElementById('header-menu-panel');
    assert.deepEqual(buttonIds(narrowPanel), FOLD_ORDER,
        'narrow: the fold targets belong in the panel');
    assert.deepEqual(buttonIds(narrow.controls), [],
        'narrow: nothing but the trigger stays inline');
    assert.equal(narrow.controls.classList.contains('controls--folded'), true,
        'narrow: .controls--folded must be set, which is what shows the trigger');

    const wide = load({ mobile: false });
    const widePanel = wide.env.document.getElementById('header-menu-panel');
    assert.deepEqual(buttonIds(widePanel), [],
        'wide: the panel must be empty - nothing needs a door');
    assert.deepEqual(
        buttonIds(wide.controls).slice().sort(),
        FOLD_ORDER.slice().sort(),
        'wide: every control the panel would have held is inline instead');
    assert.equal(wide.controls.classList.contains('controls--folded'), false,
        'wide: .controls--folded must be absent, which is what hides the trigger');
});

test('THE PHONE STRIP FOLDS THE HEADER AT 769 TO 1023 PX TOO, so its kebab is never empty (#1551, D12)', () => {
    const wide = load({ mobile: false });
    const panel = wide.env.document.getElementById('header-menu-panel');
    assert.deepEqual(buttonIds(panel), [], 'wide, no strip: nothing folded');
    wide.menu.setStripOwnsBar(true);
    assert.deepEqual(buttonIds(panel), FOLD_ORDER, 'strip up: every control, files and notes included, is in the panel');
    wide.menu.setStripOwnsBar(false);
    assert.deepEqual(buttonIds(panel), [], 'strip gone: back inline');
});

test('client/css/header-menu.css shows the trigger only while .controls--folded is set', () => {
    const css = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'css', 'header-menu.css'), 'utf8');
    assert.match(css, /\.header-menu-toggle\s*\{[^}]*display:\s*none/,
        'the trigger must be hidden by default');
    assert.match(css, /\.controls--folded\s+\.header-menu-toggle\s*\{[^}]*display:\s*inline-flex/,
        'the trigger must only be revealed under .controls--folded');
});

test('a width change cannot duplicate or drop a control, in either direction, repeatedly', () => {
    const { env, controls, setMediaMatches } = load({ mobile: false });
    const panel = env.document.getElementById('header-menu-panel');
    const foldable = FOLD_ORDER;
    for (let i = 0; i < 3; i++) {
        setMediaMatches(true);
        assert.deepEqual(buttonIds(panel), foldable, `cycle ${i} narrow: panel`);
        assert.deepEqual(buttonIds(controls), [], `cycle ${i} narrow: controls`);
        assert.equal(controls.classList.contains('controls--folded'), true, `cycle ${i} narrow: folded`);

        setMediaMatches(false);
        assert.deepEqual(buttonIds(panel), [], `cycle ${i} wide: panel`);
        assert.deepEqual(buttonIds(controls).slice().sort(),
            foldable.slice().sort(), `cycle ${i} wide: controls`);
        assert.equal(controls.classList.contains('controls--folded'), false, `cycle ${i} wide: folded`);

        for (const id of foldable) {
            assert.equal(env.document.querySelectorAll(`#${id}`).length, 1,
                `${id} duplicated on cycle ${i}`);
        }
    }
});

test('a resize that stays on the same side of the boundary is a no-op', () => {
    const { env, controls, setMediaMatches } = load({ mobile: true });
    const theme = env.document.getElementById('headerSessionThemeBtn');
    setMediaMatches(true);
    assert.equal(env.document.getElementById('headerSessionThemeBtn'), theme,
        'the same node must still be found by id');
    assert.equal(controls.classList.contains('controls--folded'), true);
});

test('the trigger stays last in the row', () => {
    const { env, controls } = load();
    const toggleIndex = controls.children.indexOf(
        env.document.getElementById('header-menu-toggle'));
    const editorIndex = controls.children.indexOf(
        env.document.getElementById('configEditorBtn'));
    assert.ok(toggleIndex > editorIndex,
        'the overflow trigger sits after the inline file editor');
});

test('a second init() is a no-op', () => {
    const { env, menu } = load({ mobile: true });
    menu.init();
    assert.equal(env.document.querySelectorAll('#header-menu-toggle').length, 1);
    assert.equal(env.document.querySelectorAll('#header-menu-panel').length, 1);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the dropdown starts closed and hidden', () => {
    const { env, menu } = load({ mobile: true });
    const panel = env.document.getElementById('header-menu-panel');
    assert.equal(menu.isOpen, false);
    assert.equal(panel.hidden, true);
});

test('the trigger opens and closes it, and tracks aria-expanded', () => {
    const { env, menu } = load({ mobile: true });
    const toggle = env.document.getElementById('header-menu-toggle');
    const panel = env.document.getElementById('header-menu-panel');
    toggle.dispatchEvent('click');
    assert.equal(menu.isOpen, true);
    assert.equal(panel.hidden, false);
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    toggle.dispatchEvent('click');
    assert.equal(menu.isOpen, false);
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
});

test('an outside tap closes it', () => {
    const { env, menu } = load({ mobile: true });
    env.document.getElementById('header-menu-toggle').dispatchEvent('click');
    assert.equal(menu.isOpen, true);
    const elsewhere = env.document.createElement('div');
    env.document.body.appendChild(elsewhere);
    elsewhere.dispatchEvent('click');
    assert.equal(menu.isOpen, false);
});

test('Escape closes it', () => {
    const { env, menu } = load({ mobile: true });
    env.document.getElementById('header-menu-toggle').dispatchEvent('click');
    assert.equal(menu.isOpen, true);
    env.document.body.dispatchEvent('keydown', { key: 'Escape' });
    assert.equal(menu.isOpen, false);
});

test('a key other than Escape does not close it', () => {
    const { env, menu } = load({ mobile: true });
    env.document.getElementById('header-menu-toggle').dispatchEvent('click');
    env.document.body.dispatchEvent('keydown', { key: 'a' });
    assert.equal(menu.isOpen, true);
});

test('tapping a control in the menu closes it behind them', () => {
    const { env, menu } = load({ mobile: true });
    env.document.getElementById('header-menu-toggle').dispatchEvent('click');
    env.document.getElementById('settingsBtn').dispatchEvent('click');
    assert.equal(menu.isOpen, false);
});

test('a tap on the panel padding does NOT close it', () => {
    const { env, menu } = load({ mobile: true });
    env.document.getElementById('header-menu-toggle').dispatchEvent('click');
    env.document.getElementById('header-menu-panel').dispatchEvent('click');
    assert.equal(menu.isOpen, true);
});

test('every control in the menu keeps an accessible name', () => {
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    for (const id of EXPECTED_IDS.concat(TOOL_IDS)) {
        const at = html.indexOf(`id="${id}"`);
        assert.ok(at > 0, `${id} missing`);
        const tag = html.slice(html.lastIndexOf('<', at), html.indexOf('>', at));
        assert.match(tag, /aria-label="[^"]+"/, `${id} needs an accessible name`);
    }
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'header-menu.js'), 'utf8');
    assert.match(src, /setAttribute\('aria-label', catalogText\('header\.menu\.more_actions'\)\)/);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the dropdown does not dismiss on focus loss', () => {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'header-menu.js'), 'utf8');
    assert.ok(!/addEventListener\(\s*['"]focusout['"]/.test(src));
    assert.ok(!/addEventListener\(\s*['"]blur['"]/.test(src));
    assert.ok(!/addEventListener\(\s*['"]focusin['"]/.test(src));
});

test('a click on an input inside the dropdown does not close it', () => {
    const { env, menu } = load({ mobile: true });
    env.document.getElementById('header-menu-toggle').dispatchEvent('click');
    const panel = env.document.getElementById('header-menu-panel');
    const input = env.document.createElement('input');
    input.type = 'text';
    panel.appendChild(input);
    input.dispatchEvent('input');
    assert.equal(menu.isOpen, true, 'typing must not close the dropdown');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
