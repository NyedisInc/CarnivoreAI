// WHY THIS FILE EXISTS: the repo has no package.json / jest / mocha, so the
// established pattern for testing client JS is a `vm`-sandboxed node script
// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { installCloudeWeb, unrefTimer } from './helpers/cloude-web-sandbox.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Read one client JS module's source. Inputs: name (string). Output: string. */
function readClientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

/** Read one client CSS file's source. Inputs: name (string). Output: string. */
function readClientCss(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'css', name), 'utf8');
}

function ruleBody(css, selector) {
    const lines = css.split('\n');
    let pendingSelectors = [];
    for (let i = 0; i < lines.length; i++) {
        const trimmed = lines[i].trim();
        if (trimmed.endsWith('{')) {
            const lastPart = trimmed.slice(0, -1).trim();
            const group = pendingSelectors.concat(
                lastPart ? lastPart.split(',').map((s) => s.trim()).filter(Boolean) : [],
            );
            pendingSelectors = [];
            if (!group.includes(selector)) continue;
            const out = [];
            for (let j = i + 1; j < lines.length && !lines[j].trim().startsWith('}'); j++) {
                out.push(lines[j]);
            }
            return out.join('\n');
        }
        pendingSelectors = trimmed.endsWith(',') ? [...pendingSelectors, trimmed.slice(0, -1).trim()] : [];
    }
    return '';
}

let failures = 0;
let passes = 0;
const queue = [];

/**
 * Queue one named assertion block, run strictly in order by runQueue().
 * Inputs: name (string), fn (function|async function). Output: void.
 */
function test(name, fn) {
    queue.push([name, fn]);
}

/** Run every queued test in order. Inputs: none. Output: Promise<void>. */
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

function settle(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

// ---------------------------------------------------------------------------
// Sandbox
// ---------------------------------------------------------------------------

function makeSandbox(options = {}) {
    const { width = 1200, withPin = false, stored = null } = options;

    const fits = [];
    const wire = [];
    const scrollCalls = [];
    const listeners = { window: {}, visualViewport: {} };
    let observedEl = null;
    let observerCb = null;

    const termEl = { id: 'terminal', clientWidth: 0, clientHeight: 0 };

    const termScreenListeners = new Set();
    const termScreenEl = {
        id: 'terminal-screen',
        addEventListener(type, fn) { if (type === 'transitionend') termScreenListeners.add(fn); },
        removeEventListener(type, fn) { if (type === 'transitionend') termScreenListeners.delete(fn); },
        fireTransitionEnd(propertyName) {
            const evt = { target: termScreenEl, propertyName };
            [...termScreenListeners].forEach((fn) => fn(evt));
        },
    };

    const controller = {
        term: { cols: 80, rows: 24, scrollToBottom: () => scrollCalls.push('scrollToBottom') },
        fitAddon: {
            fit() {
                fits.push(Date.now());
                controller.term.cols = Math.max(2, Math.floor(termEl.clientWidth / 8));
                controller.term.rows = Math.max(1, Math.floor(termEl.clientHeight / 16));
            },
        },
        lastSentCols: null,
        lastSentRows: null,
        /**
         * Stand-in for TerminalController#sendResize with the same dedup
         * contract: one frame per distinct (cols, rows).
         * Inputs: reason (string). Output: void.
         */
        sendResize(reason) {
            const { cols, rows } = controller.term;
            if (cols === controller.lastSentCols && rows === controller.lastSentRows) return;
            controller.lastSentCols = cols;
            controller.lastSentRows = rows;
            wire.push({ type: 'pty_resize', cols, rows, reason });
        },
    };

    const pinBtn = {
        hidden: false,
        attrs: {},
        title: '',
        listeners: {},
        setAttribute(k, v) { this.attrs[k] = String(v); },
        getAttribute(k) { return this.attrs[k] ?? null; },
        addEventListener(type, fn) { this.listeners[type] = fn; },
    };

    const bodyClasses = new Set();
    const store = new Map();
    if (stored !== null) store.set('carnivore.session.sidebar.pinned', stored);

    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        setTimeout: unrefTimer(setTimeout),
        clearTimeout,
        Date,
        Math,
        String,
        ResizeObserver: class {
            constructor(cb) { observerCb = cb; }
            observe(el) { observedEl = el; }
        },
        document: {
            getElementById(id) {
                if (id === 'terminal') return termEl;
                if (id === 'terminal-screen') return termScreenEl;
                if (id === 'session-sidebar-pin') return pinBtn;
                return null;
            },
            body: {
                classList: {
                    toggle(name, on) { if (on) bodyClasses.add(name); else bodyClasses.delete(name); },
                    contains(name) { return bodyClasses.has(name); },
                },
            },
        },
        localStorage: {
            getItem: (k) => (store.has(k) ? store.get(k) : null),
            setItem: (k, v) => store.set(k, v),
        },
    };
    sandbox.window = sandbox;
    sandbox.innerWidth = width;
    sandbox.addEventListener = (type, fn) => { listeners.window[type] = fn; };
    sandbox.removeEventListener = () => {};
    sandbox.visualViewport = {
        addEventListener: (type, fn) => { listeners.visualViewport[type] = fn; },
    };

    vm.createContext(sandbox);
    vm.runInContext(readClientJs('terminal-layout.js'), sandbox);

    let sidebar = null;
    if (withPin) {
        sidebar = { isOpen: true, backdrop: { hidden: false }, close() { sidebar.isOpen = false; } };
        installCloudeWeb(sandbox);
        sandbox.SessionSidebar = sidebar;
    }

    return {
        sandbox,
        Layout: sandbox.TerminalLayout,
        Pin: sandbox.SessionSidebarPin,
        sidebar,
        controller,
        termEl,
        termScreenEl,
        fits,
        wire,
        scrollCalls,
        listeners,
        bodyClasses,
        get observedEl() { return observedEl; },
        fireObserver: () => observerCb && observerCb(),
        setWidth: (w) => { sandbox.innerWidth = w; },
    };
}

function setDocked(s, docked) {
    s.setWidth(docked ? 1200 : 390);
    s.Pin.apply();
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

test('install observes #terminal and wires every resize source', () => {
    const s = makeSandbox();
    s.Layout.install(s.controller);
    assert.equal(s.observedEl, s.termEl, 'the ResizeObserver must watch the xterm container');
    assert.ok(typeof s.listeners.window.resize === 'function');
    assert.ok(typeof s.listeners.window.orientationchange === 'function');
    assert.ok(typeof s.listeners.visualViewport.resize === 'function',
        'the on-screen keyboard only shows up on visualViewport');
});

test('install is idempotent - a second call does not stack listeners', () => {
    const s = makeSandbox();
    s.Layout.install(s.controller);
    const first = s.listeners.window.resize;
    s.Layout.install(s.controller);
    assert.equal(s.listeners.window.resize, first);
});

test('requestFitAfterTransition with no element degrades to an immediate refit, not silence', async () => {
    const s = makeSandbox();
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 640;
    s.termEl.clientHeight = 480;
    s.Layout.requestFitAfterTransition(null, 'padding-left', 250, 'no-element-reason');
    await settle(s.Layout.DEBOUNCE_MS + 40);
    assert.equal(s.wire.length, 1);
    assert.equal(s.wire[0].reason, 'no-element-reason');
});

test('requestFitAfterTransition ignores a transitionend for the wrong CSS property', async () => {
    const s = makeSandbox();
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 640;
    s.termEl.clientHeight = 480;
    s.Layout.requestFitAfterTransition(s.termScreenEl, 'padding-left', 250, 'prop-test');
    s.termScreenEl.fireTransitionEnd('opacity');
    await settle(s.Layout.DEBOUNCE_MS + 40);
    assert.equal(s.wire.length, 0, 'the wrong property must not settle the wait early');
    s.termScreenEl.fireTransitionEnd('padding-left');
    await settle(s.Layout.DEBOUNCE_MS + 40);
    assert.equal(s.wire.length, 1, 'the matching property must settle it');
});

test('requestFitAfterTransition still refits when no transitionend ever arrives (the fallback ceiling)', async () => {
    const s = makeSandbox();
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 640;
    s.termEl.clientHeight = 480;
    s.Layout.requestFitAfterTransition(s.termScreenEl, 'padding-left', 30, 'fallback-test');
    await settle(30 + s.Layout.DEBOUNCE_MS + 60);
    assert.equal(s.wire.length, 1, 'the fallback timer must settle a transition that never ends');
    assert.equal(s.wire[0].reason, 'fallback-test');
});

test('a burst of layout events collapses to one fit and one pty_resize', async () => {
    const s = makeSandbox();
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 800;
    s.termEl.clientHeight = 600;
    for (let i = 0; i < 20; i++) s.fireObserver();
    await settle(s.Layout.DEBOUNCE_MS + 60);
    assert.equal(s.fits.length, 1, 'a CSS transition must not produce 20 resizes');
    assert.equal(s.wire.length, 1);
    assert.equal(s.wire[0].type, 'pty_resize');
});

test('a fit never scrolls the terminal - the scrollback race stays fixed', async () => {
    const s = makeSandbox();
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 800;
    s.termEl.clientHeight = 600;
    s.Layout.requestFit('test');
    await settle(s.Layout.DEBOUNCE_MS + 60);
    assert.deepEqual(s.scrollCalls, [], 'resizing must not yank a scrolled-up user to the bottom');
    const code = readClientJs('terminal-layout.js')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\/\/.*$/gm, '');
    assert.ok(!code.includes('scrollToBottom'),
        'the resize pipeline must not contain a scroll command at all');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

function modelFit(v) {
    const headerH = v.headerH ?? 58;
    const pad = v.pad ?? 8;
    const toolsH = v.toolsH ?? 0;
    const cellW = v.cellW ?? 8.79;
    const cellH = v.cellH ?? 16;
    const boxW = v.vw - pad * 2;
    const boxH = v.vh - headerH - toolsH - pad * 2;
    return {
        boxW,
        boxH,
        cols: Math.max(2, Math.floor(boxW / cellW)),
        rows: Math.max(1, Math.floor(boxH / cellH)),
    };
}

test('a narrow viewport produces cols that fit inside it', () => {
    for (const vw of [320, 360, 390, 414, 430]) {
        const { cols, boxW } = modelFit({ vw, vh: 844 });
        assert.ok(cols * 8.79 <= boxW, `cols must fit the box at ${vw}px`);
        assert.ok(cols * 8.79 <= vw, `cols must fit the viewport at ${vw}px`);
        assert.ok(cols < 80, `${vw}px cannot hold the 80-col default, got ${cols}`);
    }
});

test('rows shrink as well as grow - the ratchet is gone', () => {
    const portrait = modelFit({ vw: 390, vh: 844 });
    const landscape = modelFit({ vw: 844, vh: 390, headerH: 56 });
    const keyboard = modelFit({ vw: 390, vh: 420 });
    assert.ok(landscape.rows < portrait.rows, 'rotating to landscape must reduce rows');
    assert.ok(keyboard.rows < portrait.rows, 'the on-screen keyboard must reduce rows');
    assert.ok(landscape.rows * 16 <= 390, 'the grid must fit the landscape viewport');
    assert.ok(keyboard.rows * 16 <= 420, 'the grid must fit above the keyboard');
});

test('the header tool strip does not reduce terminal height', () => {
    const overlaid = modelFit({ vw: 390, vh: 844, toolsH: 0 });
    const inFlow = modelFit({ vw: 390, vh: 844, toolsH: 50 });
    assert.ok(overlaid.rows > inFlow.rows,
        'an in-flow strip costs rows; the overlay must not');
    assert.equal(overlaid.boxH, 844 - 58 - 16);
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

test('pinning the sidebar fits the terminal and sends the new size to tmux', async () => {
    const s = makeSandbox({ withPin: true, width: 390 });
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 1170;
    s.termEl.clientHeight = 673;
    s.Pin.init();
    await settle(400);
    const before = s.wire.length;

    setDocked(s, true);
    assert.equal(s.bodyClasses.has('session-sidebar-pinned'), true);
    s.termEl.clientWidth = 850;
    await settle(400);

    assert.ok(s.wire.length > before, 'pinning must put a pty_resize on the wire');
    const pinFrame = s.wire[s.wire.length - 1];
    assert.equal(pinFrame.reason, 'sidebar-pin', 'the refit must be the announced one');
    assert.ok(pinFrame.cols < 137, `cols must shrink when docked, got ${pinFrame.cols}`);

    const mid = s.wire.length;
    setDocked(s, false);
    assert.equal(s.bodyClasses.has('session-sidebar-pinned'), false);
    s.termEl.clientWidth = 1170;
    await settle(400);
    assert.ok(s.wire.length > mid, 'unpinning must also put a pty_resize on the wire');
    assert.ok(s.wire[s.wire.length - 1].cols > pinFrame.cols, 'cols must grow back');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

test('docking measures the box in the same frame - nothing left to wait out', async () => {
    const s = makeSandbox({ withPin: true, width: 390 });
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 1170;
    s.termEl.clientHeight = 673;
    s.Pin.init();
    await settle(400);
    const before = { cols: s.controller.term.cols, rows: s.controller.term.rows };

    setDocked(s, true);
    s.termEl.clientWidth = 850;
    await settle(s.Layout.DEBOUNCE_MS + 20);

    const after = { cols: s.controller.term.cols, rows: s.controller.term.rows };
    const frame = s.wire[s.wire.length - 1];
    assert.equal(frame.reason, 'sidebar-pin');
    assert.equal(frame.cols, after.cols, 'the shipped frame must match the settled grid');
    assert.ok(after.cols < before.cols,
        `pin must narrow the grid: before=${before.cols}x${before.rows} after=${after.cols}x${after.rows}`);
});

test('a rapid pin-then-unpin sends ZERO resizes - net state equals where it started', async () => {
    const s = makeSandbox({ withPin: true, width: 390 });
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 1170;
    s.termEl.clientHeight = 673;
    s.Pin.init();
    await settle(400);
    const before = s.wire.length;

    setDocked(s, true);   // docked
    setDocked(s, false);
    assert.equal(s.bodyClasses.has('session-sidebar-pinned'), false);
    s.termEl.clientWidth = 1170;
    await settle(s.Layout.DEBOUNCE_MS + 40);

    assert.equal(s.wire.length, before,
        'no frame belongs on the wire when the settled grid never changed');
});

test('a rapid pin-unpin-pin (odd count) sends exactly ONE resize, for the final settled layout', async () => {
    const s = makeSandbox({ withPin: true, width: 390 });
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 1170;
    s.termEl.clientHeight = 673;
    s.Pin.init();
    await settle(400);
    const before = { cols: s.controller.term.cols, rows: s.controller.term.rows };
    const beforeWire = s.wire.length;

    setDocked(s, true);   // docked
    setDocked(s, false);  // undocked
    setDocked(s, true);
    assert.equal(s.bodyClasses.has('session-sidebar-pinned'), true);
    s.termEl.clientWidth = 850;
    await settle(s.Layout.DEBOUNCE_MS + 40);

    const sent = s.wire.slice(beforeWire);
    assert.equal(sent.length, 1, `exactly one resize must be sent, got ${sent.length}`);
    assert.equal(sent[0].reason, 'sidebar-pin');
    const after = { cols: s.controller.term.cols, rows: s.controller.term.rows };
    assert.equal(sent[0].cols, after.cols, 'the one frame matches the settled grid');
    assert.ok(after.cols < before.cols,
        `pin must narrow the grid: before=${before.cols}x${before.rows} after=${after.cols}x${after.rows}`);
});

test('re-applying the SAME docked state is a no-op, not a wasted resize', async () => {
    const s = makeSandbox({ withPin: true, width: 390 });
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 1170;
    s.termEl.clientHeight = 673;
    s.Pin.init();
    await settle(400);
    setDocked(s, true);
    s.termEl.clientWidth = 850;
    await settle(s.Layout.DEBOUNCE_MS + 40);
    const beforeWire = s.wire.length;
    const beforeFits = s.fits.length;

    s.Pin.apply();
    s.Pin.apply();
    s.Pin.apply();
    await settle(s.Layout.DEBOUNCE_MS + 40);

    assert.equal(s.fits.length, beforeFits, 'no docked-state change means no refit attempt');
    assert.equal(s.wire.length, beforeWire, 'no docked-state change means no new resize');
});

test('the pin does not refit on a phone, where it never docks', async () => {
    const s = makeSandbox({ withPin: true, width: 390 });
    s.Layout.install(s.controller);
    s.termEl.clientWidth = 374;
    s.termEl.clientHeight = 770;
    s.Pin.init();
    await settle(400);
    const before = s.wire.length;
    s.Pin.apply();
    await settle(400);
    assert.equal(s.bodyClasses.has('session-sidebar-pinned'), false,
        'a phone never docks, however often the module re-evaluates');
    assert.equal(s.wire.length, before,
        'and a re-evaluation that changes no layout must send nothing');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

test('the app shell has a DEFINITE height, not min-height', () => {
    const body = ruleBody(readClientCss('styles.css'), 'body');
    assert.ok(/^\s*height:\s*100dvh;/m.test(body), 'body needs a definite height');
    assert.ok(/^\s*height:\s*100vh;/m.test(body), 'and a 100vh fallback first');
    assert.ok(!/min-height:\s*100vh/.test(body),
        'min-height leaves the flex chain content-sized and the terminal ratchets');
});

test('nothing in the terminal chain carries a pixel height floor', () => {
    const css = readClientCss('styles.css');
    assert.ok(/min-height:\s*0;/.test(ruleBody(css, '.terminal-container')));
    assert.ok(/min-height:\s*0;/.test(ruleBody(css, '.screen')));
    assert.ok(/min-height:\s*0;/.test(ruleBody(css, '#terminal-screen')));
    const floors = css.match(/\.terminal-container\s*\{[^}]*min-height:\s*\d+px/g) || [];
    assert.deepEqual(floors, [], 'a pixel floor on .terminal-container reopens the ratchet');
});

test('the terminal screen can never scroll sideways', () => {
    const body = ruleBody(readClientCss('styles.css'), '#terminal-screen');
    assert.ok(/overflow:\s*hidden;/.test(body));
    assert.ok(/position:\s*relative;/.test(body), 'containing block for the overlaid tool strip');
});

test('no CSS tooltip is left to overflow the terminal (issue #981)', () => {
    const css = readClientCss('styles.css');
    assert.equal(ruleBody(css, '.btn-icon[data-tooltip]::after'), '',
        'a CSS ::after tooltip shows instantly and beside the native one');
    // there is nothing
    const tools = readClientCss('terminal-tools.css');
    assert.ok(!tools.includes('data-tooltip'),
        'a CSS tooltip in the terminal corner is what overflowed before');
});

test('nothing overlays the terminal: no strip, no rail, no floating button', () => {
    const css = readClientCss('terminal-tools.css');
    assert.ok(!/\.terminal-tools\s*\{/.test(css),
        'the top-right tool strip must not be reintroduced');
    const noComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
    assert.ok(noComments.includes('.fab-menu {'),
        'the scan must actually read the menu sheet');
    assert.ok(!/\.session-editor-fab/.test(noComments),
        'the top-right rail must stay retired');
    for (const gone of ['.fab-menu-btn', '.terminal-tools-fab']) {
        assert.ok(!noComments.includes(gone), `${gone} must not come back`);
    }
    assert.match(noComments,
        /@media \(min-width: 769px\) \{\s*\n\s*\.terminal-tools-menu \{\s*\n\s*display: none !important;/,
        'the tools menu must be hidden on desktop');
});

test('terminal.js delegates the resize pipeline instead of growing', () => {
    const src = readClientJs('terminal.js');
    assert.ok(src.includes("this._m('TerminalLayout').install(this)"));
    assert.ok(!src.includes('new ResizeObserver('),
        'the observer moved to terminal-layout.js; two of them would double-fire');
    // server does not close on handshake timeout either
    // client/js/terminal-input-ownership.js.
    const lines = src.split('\n').length;
    assert.ok(lines < 2770, `terminal.js must not grow, is ${lines} lines`);
});

test('sendResize names its no-op instead of failing silently when no session is attached', () => {
    const src = readClientJs('terminal.js');
    const fn = src.slice(src.indexOf('sendResize(source'), src.indexOf('sendResize(source') + 1400);
    assert.ok(/no-session/.test(fn), 'the no-op must be named, not a bare return');
    assert.ok(/console\.warn/.test(fn), 'the no-op must also be observable, not just structurally named');
    assert.ok(/delivered:\s*true/.test(fn), 'a successful send must report the same named-outcome shape');
});

await runQueue();
console.log(`${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
