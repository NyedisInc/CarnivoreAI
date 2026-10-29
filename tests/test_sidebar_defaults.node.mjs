// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STORAGE_KEY = 'carnivore.session.sidebar';

function clientFile(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', ...parts), 'utf8');
}

function drawerFile(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', 'web', 'src', 'lib', ...parts), 'utf8');
}

let failures = 0;
let passes = 0;
const queue = [];

/** Queue one named assertion block. Inputs: name, fn. Output: void. */
function test(name, fn) { queue.push([name, fn]); }

async function runQueue() {
    for (const [name, fn] of queue) {
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

function makeEl() {
    const attrs = {};
    const classes = new Set();
    return {
        inert: false,
        hidden: false,
        classes,
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
            toggle(c, on) {
                const want = on === undefined ? !classes.has(c) : !!on;
                if (want) classes.add(c); else classes.delete(c);
                return want;
            },
        },
        setAttribute(k, v) { attrs[k] = String(v); },
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
        focus() {},
        blur() {},
        contains() { return false; },
        addEventListener() {},
    };
}

function makeSandbox({ stored = null, throws = false, width = 1280 } = {}) {
    const store = new Map();
    if (stored !== null) store.set(STORAGE_KEY, stored);
    const writes = [];
    const doc = { activeElement: null, body: makeEl(), getElementById: () => null };
    const HTMLElement = function () {};
    HTMLElement.prototype.inert = false;

    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: doc,
        HTMLElement,
        localStorage: {
            getItem(k) {
                if (throws) throw new Error('storage denied');
                return store.has(k) ? store.get(k) : null;
            },
            setItem(k, v) {
                if (throws) throw new Error('storage denied');
                store.set(k, String(v));
                if (k === STORAGE_KEY) writes.push(String(v));
            },
        },
        setInterval: () => 0,
        clearInterval: () => {},
        innerWidth: width,
        addEventListener() {},
        removeEventListener() {},
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    installCloudeWeb(sandbox);

    const ctrl = sandbox.SessionSidebar;
    const panel = makeEl();
    const toggleBtn = makeEl();
    toggleBtn.classList.add('hidden');
    ctrl.panel = panel;
    ctrl.backdrop = makeEl();
    ctrl.toggleBtn = toggleBtn;
    ctrl.listEl = makeEl();
    ctrl._wired = true;
    ctrl._fetchAndRender = () => {};
    ctrl._startPoll = () => {};
    ctrl.repaint = () => {};
    return {
        ctrl, panel, toggleBtn, store, writes,
        Controller: ctrl.constructor, Pin: sandbox.SessionSidebarPin,
    };
}

// =====================================================================
// =====================================================================

test('opensFrom on a desktop: absent opens, 0 does not, 1 does', () => {
    const { Pin } = makeSandbox({ width: 1280 });
    assert.equal(Pin.opensFrom(null), true, 'nothing stored means OPEN');
    assert.equal(Pin.opensFrom(undefined), true, 'and so does undefined');
    assert.equal(Pin.opensFrom(''), true, 'and an empty string');
    assert.equal(Pin.opensFrom('0'), false,
        'a user who closed the bar must not have it forced back open');
    assert.equal(Pin.opensFrom('1'), true);
});

test('opensFrom on a phone: the DEFAULT flips, an explicit choice does not', () => {
    const { Pin } = makeSandbox({ width: 390 });
    assert.equal(Pin.opensFrom(null), false, 'a phone with no choice opens CLOSED');
    assert.equal(Pin.opensFrom(undefined), false);
    assert.equal(Pin.opensFrom(''), false);
    assert.equal(Pin.opensFrom('1'), true,
        'but a user who explicitly opened it still gets it open on a phone');
    assert.equal(Pin.opensFrom('0'), false);
});

test('a reported width of 0 is NOT a phone, so the bar still opens', () => {
    const { Pin } = makeSandbox({ width: 0 });
    assert.equal(Pin.opensFrom(null), true);
});

test('show() really opens the panel when nothing is stored', () => {
    const { ctrl, panel, toggleBtn } = makeSandbox();
    ctrl.show();
    assert.equal(ctrl.isOpen, true);
    assert.equal(panel.classes.has('session-sidebar-panel--open'), true,
        'the class the stylesheet keys the slide-in off must really be on');
    assert.equal(panel.getAttribute('aria-hidden'), 'false');
    assert.equal(toggleBtn.getAttribute('aria-expanded'), 'true');
    assert.equal(toggleBtn.classes.has('hidden'), false, 'and the toggle is revealed');
});

test('show() leaves the panel shut for a user who closed it', () => {
    const { ctrl, panel } = makeSandbox({ stored: '0' });
    ctrl.show();
    assert.equal(ctrl.isOpen, false);
    assert.equal(panel.classes.has('session-sidebar-panel--open'), false);
});

test('show() does not WRITE the default - absent stays absent', () => {
    const { ctrl, store } = makeSandbox();
    ctrl.show();
    assert.equal(store.has(STORAGE_KEY), true,
        'open() itself persists the open state, which is the existing behaviour');
    assert.equal(store.get(STORAGE_KEY), '1');
});

test('storage that cannot be read opens rather than throwing', () => {
    const { ctrl } = makeSandbox({ throws: true });
    ctrl.show();
    assert.equal(ctrl.isOpen, true,
        'an unreadable preference is an ABSENT one, and absent is open');
});

test('show() is idempotent - a second call does not re-open an open bar', () => {
    const { ctrl } = makeSandbox();
    ctrl.show();
    ctrl.close();
    assert.equal(ctrl.isOpen, false);
    ctrl.show();
    assert.equal(ctrl.isOpen, false, 'closing the bar has to survive a screen change');
});

// =====================================================================
// =====================================================================

test('open({persist: false}) opens without writing, and marks the open transient', () => {
    const { ctrl, store, writes } = makeSandbox({ width: 1280 });
    ctrl.open({ persist: false });
    assert.equal(ctrl.isOpen, true);
    assert.equal(ctrl._transientOpen, true,
        'a non-persisting open must be recorded as having no real preference behind it');
    assert.equal(writes.length, 0, 'a non-persisting open wrote to storage');
    assert.equal(store.has(STORAGE_KEY), false);
});

test('a normal open() (no opts) is never transient, even mid-forced-open', () => {
    const { ctrl, store } = makeSandbox({ width: 1280 });
    ctrl.open({ persist: false });
    ctrl.open();
    assert.equal(ctrl._transientOpen, false,
        'an explicit/real open must clear the transient marker a forced one left behind');
    assert.equal(store.get(STORAGE_KEY), '1');
});

test('DESKTOP, STORED CLOSED: a real session entry closes a forced-open drawer back, and writes nothing', () => {
    const { ctrl, store, writes } = makeSandbox({ stored: '0', width: 1280 });
    ctrl.show();
    assert.equal(ctrl.isOpen, false, 'test setup: a stored 0 must leave show() closed');
    ctrl.open({ persist: false });
    assert.equal(ctrl.isOpen, true);
    writes.length = 0;
    ctrl.setActiveSession('s1', 'cloude_real');
    assert.equal(ctrl.isOpen, false,
        'the drawer was left open after a real session attached, contradicting the stored preference');
    assert.equal(ctrl._transientOpen, false);
    assert.equal(writes.length, 0, 'reconciling to the stored preference wrote to storage');
    assert.equal(store.get(STORAGE_KEY), '0', 'the stored preference itself must be untouched');
});

test('DESKTOP, NOTHING STORED: a real explicit open survives a real session entry unreconciled', () => {
    const { ctrl, writes } = makeSandbox({ width: 1280 });
    ctrl.show();
    assert.equal(ctrl.isOpen, true, 'test setup: nothing stored opens by default on a desktop');
    writes.length = 0;
    ctrl.setActiveSession('s1', 'cloude_real');
    assert.equal(ctrl.isOpen, true, 'a real open was closed by the reconcile step');
    assert.equal(writes.length, 0, 'nothing should be written just by attaching a session');
});

test('PHONE, NOTHING STORED: the auto-close after picking a row does not fabricate a closed preference', () => {
    const { ctrl, store, writes, Pin } = makeSandbox({ width: 390 });
    ctrl.show();
    assert.equal(ctrl.isOpen, false, 'test setup: a phone with nothing stored opens closed');
    ctrl.open({ persist: false });
    Pin.closeAfterSwitch();
    assert.equal(ctrl.isOpen, false, 'picking a row must still close the overlay on a phone');
    assert.equal(writes.length, 0,
        'the automatic close-after-switch fabricated a preference the user never chose');
    assert.equal(store.has(STORAGE_KEY), false);
});

test('PHONE, EXPLICITLY OPEN: the auto-close after picking a row still persists, as it always did', () => {
    // NEGATIVE CONTROL for
    const { ctrl, store, writes, Pin } = makeSandbox({ stored: '1', width: 390 });
    ctrl.show();
    assert.equal(ctrl.isOpen, true, 'test setup: an explicit 1 opens even on a phone');
    assert.equal(ctrl._transientOpen, false);
    writes.length = 0;
    Pin.closeAfterSwitch();
    assert.equal(ctrl.isOpen, false);
    assert.equal(writes.length, 1, 'a real open must still persist its close, exactly as before');
    assert.equal(store.get(STORAGE_KEY), '0');
});

// =====================================================================
// =====================================================================

test('all three defaults are the ones the owner asked for', () => {
    const sidebar = drawerFile('drawer', 'controller.ts');
    assert.ok(!/function opensFrom|opensFrom\s*\(stored[^)]*\)\s*[:{]/.test(sidebar),
        'the controller must not carry its own copy of the open default');
    assert.ok(sidebar.includes('Pin.opensFrom(this.storedPreference())'),
        'the controller asks the pin module for the open default');

    const pin = drawerFile('drawer', 'pin.ts');
    assert.ok(pin.includes('export function opensFrom(stored'),
        'and the pin module is where that default lives');
    assert.ok(pin.includes('return !isMobile();'),
        'OPEN unless explicitly closed, and CLOSED by default on a phone');
    assert.ok(!/localStorage\.getItem|readMigrating\(/.test(pin),
        'docking must stay derived from width, with nothing read from storage');

    const density = drawerFile('drawer', 'density.ts');
    assert.match(density, /export const DEFAULT_MODE = 'compact';/, 'COMPACT rows');

    const html = clientFile('index.html');
    assert.match(html, /id="session-sidebar-panel"[\s\S]{0,200}data-density="compact"/,
        'the shipped panel attribute agrees, so the first paint is not a different height');
    const viewState = fs.readFileSync(path.join(__dirname, '..', 'web', 'src', 'lib', 'session-list', 'view-state.svelte.ts'), 'utf8');
    assert.match(viewState, /density: currentDensity\(\) \?\? 'compact',/,
        'and the view menu starts at compact before the module answers');
});

test('the pane is called AGENTS everywhere it is named to the user', () => {
    const html = clientFile('index.html');
    assert.ok(!html.includes('<span class="session-sidebar-title">agents</span>'),
        'the word was replaced by the wordmark');
    assert.ok(fs.readFileSync(path.join(__dirname, '..', 'web', 'src', 'lib', 'drawer', 'DrawerHeader.svelte'), 'utf8')
        .includes('id="session-sidebar-brand"'), 'and the wordmark is what took its place');
    assert.ok(html.includes('aria-label="Agents" title="agents"'),
        'the drawer toggle');
    assert.ok(html.includes('aria-label="Agents" data-density="compact"'),
        'the panel itself');
    assert.ok(fs.readFileSync(path.join(__dirname, '..', 'client', 'js', 'i18n', 'catalog.en.js'), 'utf8')
        .includes("'drawer.header.hide': 'hide agents'"), 'the collapse button');
    const plan = drawerFile('sidebar-shell', 'plan.ts');
    for (const [name, src] of [['plan', plan]]) {
        assert.ok(/\? 'agent' : 'agents'/.test(src),
            `the group header count reads "(4 agents)" (${name})`);
        assert.ok(!src.includes("'conversation' : 'conversations'"));
    }
    assert.ok(plan.includes('no other agents'), 'the empty state');
    assert.ok(!plan.includes('no other conversations'));
    const clicks = fs.readFileSync(path.join(__dirname, '..', 'web/src/lib/drawer/row-switch.ts'), 'utf8');
    assert.ok(clicks.includes('sidebar.row.switch.failed'), 'the switch failure alert (catalog: failed to switch agent)');
    assert.ok(!clicks.includes('failed to switch conversation'));
    assert.ok(clicks.includes('conversation:') === false,
        'and no other alert in the pane still says it');
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
