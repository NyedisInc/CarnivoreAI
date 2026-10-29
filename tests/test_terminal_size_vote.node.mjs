// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import { TerminalProvider } from '../web/src/lib/terminal-provider/provider.ts';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const VOTE_SRC = read('client/js/terminal-size-vote.js');
const LAYOUT_SRC = read('client/js/terminal-layout.js');
const TERM_SRC = read('client/js/terminal.js');
const INDEX_HTML = read('client/index.html');
const TERM_SINGLETON = '// THE CLASS ENDS ABOVE.';

function fakeDocument() {
    const listeners = {};
    return {
        visibilityState: 'visible',
        listeners,
        addEventListener(type, fn) { (listeners[type] ||= new Set()).add(fn); },
        removeEventListener(type, fn) { listeners[type]?.delete(fn); },
        fire(type) { [...(listeners[type] || [])].forEach((fn) => fn({ type })); },
        getElementById() { return null; },
    };
}

function fakeWeb() {
    return {
        calls: [],
        showTerminalSizeNotice(cols, rows) { this.calls.push(['show', cols, rows]); },
        clearTerminalSizeNotice() { this.calls.push(['clear']); },
    };
}

function makeSandbox(extra = []) {
    const document = fakeDocument();
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout, clearTimeout, Date, Math, String, JSON,
        document,
        requestAnimationFrame() {
            throw new Error('requestAnimationFrame never resolves in a hidden tab');
        },
        WebSocket: { OPEN: 1 },
    };
    sandbox.window = sandbox;
    sandbox.addEventListener = () => {};
    sandbox.removeEventListener = () => {};
    sandbox.CloudeWeb = fakeWeb();
    sandbox.TerminalProvider = TerminalProvider;
    vm.createContext(sandbox);
    vm.runInContext(VOTE_SRC, sandbox, { filename: 'terminal-size-vote.js' });
    for (const [src, name] of extra) vm.runInContext(src, sandbox, { filename: name });
    return sandbox;
}

function recordingController(sandbox) {
    const sent = [];
    const fits = [];
    sandbox.TerminalMetrics = {
        guardedFit(ctl) { fits.push(ctl); return { fitted: true }; },
        enforceWidthFit() { return { changed: false }; },
    };
    return {
        sent, fits,
        term: { cols: 160, rows: 47 },
        fitAddon: { fit() {} },
        sendResize(reason, force) { sent.push([reason, force]); },
    };
}


test('TerminalLayout.install wires visibilitychange: hidden withdraws, visible rejoins', () => {
    const sandbox = makeSandbox([[LAYOUT_SRC, 'terminal-layout.js']]);
    const ctl = recordingController(sandbox);
    const layout = sandbox.TerminalLayout.create();
    layout.install(ctl);

    sandbox.document.visibilityState = 'hidden';
    sandbox.document.fire('visibilitychange');
    assert.deepEqual(ctl.sent, [['visibility.hidden', true]],
        'going hidden must re-send the grid, FORCED past the dedup');
    assert.equal(ctl.fits.length, 0, 'nothing is measured while hidden');

    sandbox.document.visibilityState = 'visible';
    sandbox.document.fire('visibilitychange');
    assert.equal(ctl.fits.length, 1, 'coming back refits first');
    assert.deepEqual(ctl.sent[1], ['visibility.visible', true]);
});

test('uninstall takes the visibility listener off again', () => {
    const sandbox = makeSandbox([[LAYOUT_SRC, 'terminal-layout.js']]);
    const ctl = recordingController(sandbox);
    const layout = sandbox.TerminalLayout.create();
    layout.install(ctl);
    assert.equal(sandbox.document.listeners.visibilitychange.size, 1, 'setup: wired');
    layout.uninstall();
    assert.equal(sandbox.document.listeners.visibilitychange.size, 0);
    sandbox.document.visibilityState = 'hidden';
    sandbox.document.fire('visibilitychange');
    assert.deepEqual(ctl.sent, []);
});

test('coming back clears the notice before rejoining, so the server re-states it', () => {
    const sandbox = makeSandbox();
    const ctl = recordingController(sandbox);
    ctl._chrome = (name) => (name === 'statusText' ? {} : null);
    sandbox.TerminalSizeVote.onVisibilityChange(ctl, sandbox.document);
    assert.deepEqual(sandbox.CloudeWeb.calls, [['clear']]);
    assert.deepEqual(ctl.sent, [['visibility.visible', true]]);
});


function realTerminalClass(sandbox) {
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    assert.notEqual(cut, -1, 'terminal.js no longer carries its class-end marker');
    vm.runInContext(TERM_SRC.slice(0, cut) + '\nwindow.__T = Terminal;',
        sandbox, { filename: 'terminal.js' });
    return sandbox.__T.prototype;
}

function resizeSelf(P, frames) {
    return {
        ws: { readyState: 1, send(text) { frames.push(JSON.parse(text)); } },
        term: { cols: 82, rows: 30 },
        lastSentCols: null, lastSentRows: null,
        _wiring: {}, _m: P._m, sendResize: P.sendResize,
    };
}

test('sendResize puts hidden: true on the wire while the tab is hidden', () => {
    const sandbox = makeSandbox();
    const P = realTerminalClass(sandbox);
    const frames = [];
    const self = resizeSelf(P, frames);

    sandbox.document.visibilityState = 'hidden';
    self.sendResize('window.resize', true);
    assert.deepEqual(frames[0], { type: 'pty_resize', cols: 82, rows: 30, hidden: true });

    sandbox.document.visibilityState = 'visible';
    self.sendResize('visibility.visible', true);
    assert.deepEqual(frames[1], { type: 'pty_resize', cols: 82, rows: 30 },
        'a visible tab sends exactly the frame every client always sent');
});

test('the handshake reply carries the flag too, so a hidden reconnect never votes', () => {
    const sandbox = makeSandbox();
    const P = realTerminalClass(sandbox);
    const frames = [];
    const self = resizeSelf(P, frames);
    self.fitAddon = {};
    self.handleWebSocketMessage = P.handleWebSocketMessage;
    sandbox.document.visibilityState = 'hidden';
    sandbox.TerminalMetrics = { guardedFit: () => ({ fitted: true }) };
    self.handleWebSocketMessage({ type: 'request_dims' });
    assert.equal(frames.length, 1);
    assert.equal(frames[0].hidden, true);
});


test('terminal_size smaller than this window paints the notice; equal clears it', () => {
    const sandbox = makeSandbox();
    const P = realTerminalClass(sandbox);
    const self = {
        _wiring: {}, _m: P._m, handleWebSocketMessage: P.handleWebSocketMessage,
        _chrome: (name) => (name === 'statusText' ? {} : null),
        lastSentCols: 160, lastSentRows: 47,
    };
    self.handleWebSocketMessage({ type: 'terminal_size', cols: 82, rows: 30, clients: 2 });
    self.handleWebSocketMessage({ type: 'terminal_size', cols: 160, rows: 47, clients: 2 });
    self.handleWebSocketMessage({ type: 'terminal_size', cols: 160, rows: 47, clients: 1 });
    assert.deepEqual(sandbox.CloudeWeb.calls, [['show', 82, 30], ['clear'], ['clear']]);
});

test('a terminal cell (no page chrome) never paints the page notice', () => {
    const sandbox = makeSandbox();
    const P = realTerminalClass(sandbox);
    const cell = {
        _wiring: {}, _m: P._m, handleWebSocketMessage: P.handleWebSocketMessage,
        _chrome: () => null, lastSentCols: 160, lastSentRows: 47,
    };
    cell.handleWebSocketMessage({ type: 'terminal_size', cols: 82, rows: 30, clients: 2 });
    assert.deepEqual(sandbox.CloudeWeb.calls, []);
});

test('constrainedBy: either axis smaller, only with another window attached', () => {
    const { TerminalSizeVote: V } = makeSandbox();
    assert.equal(V.constrainedBy({ cols: 82, rows: 47, clients: 2 }, 160, 47), true);
    assert.equal(V.constrainedBy({ cols: 160, rows: 30, clients: 2 }, 160, 47), true);
    assert.equal(V.constrainedBy({ cols: 160, rows: 47, clients: 2 }, 160, 47), false);
    assert.equal(V.constrainedBy({ cols: 82, rows: 30, clients: 1 }, 160, 47), false);
    assert.equal(V.constrainedBy({ cols: 82, rows: 30, clients: 2 }, null, null), false);
});

test('_beginConnection clears the size notice on every session switch', () => {
    const sandbox = makeSandbox();
    const P = realTerminalClass(sandbox);
    const self = { _connGen: null, _wiring: {}, _m: P._m,
        _beginConnection: P._beginConnection,
        _chrome: (name) => (name === 'statusText' ? {} : null) };
    self._beginConnection('connectToSession');
    assert.deepEqual(sandbox.CloudeWeb.calls, [['clear']]);
});

test('index.html serves the module before terminal-layout.js and terminal.js, with its container', () => {
    const order = [...INDEX_HTML.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)]
        .map((m) => m[1]);
    const at = order.indexOf('terminal-size-vote.js');
    assert.ok(at >= 0, 'the module must be in index.html or it is dead code');
    assert.ok(at < order.indexOf('terminal-layout.js'));
    assert.ok(at < order.indexOf('terminal.js'));
    assert.ok(INDEX_HTML.includes('<div id="terminal-size-notice"></div>'));
});

test('the catalog carries the notice string, lowercase and with both placeholders', () => {
    const CATALOG_SRC = read('client/js/i18n/catalog.en.js');
    const m = CATALOG_SRC.match(/'terminal\.size\.constrained':\s*'([^']*)'/);
    assert.ok(m, 'the key is missing');
    assert.match(m[1], /^[a-z]/);
    assert.ok(m[1].includes('{cols}') && m[1].includes('{rows}'));
});


test('isWithdrawn: the browser tab hidden OR the component tab hidden', () => {
    const sandbox = makeSandbox();
    const vote = sandbox.TerminalSizeVote;
    const doc = sandbox.document;
    assert.equal(vote.isWithdrawn({}, doc), false);
    assert.equal(vote.isWithdrawn({ _tabHidden: true }, doc), true);
    doc.visibilityState = 'hidden';
    assert.equal(vote.isWithdrawn({}, doc), true);
    assert.equal(vote.isWithdrawn(undefined, doc), true);
    doc.visibilityState = 'visible';
    assert.equal(vote.isWithdrawn(undefined, doc), false);
});

test('setTabHidden withdraws once, rejoins with a refit, and repeats send nothing', () => {
    const sandbox = makeSandbox();
    const ctl = recordingController(sandbox);
    const vote = sandbox.TerminalSizeVote;
    vote.setTabHidden(ctl, true, sandbox.document);
    vote.setTabHidden(ctl, true, sandbox.document);
    assert.deepEqual(ctl.sent, [['tab.hidden', true]], 'one forced withdrawal, no repeat');
    assert.equal(ctl.fits.length, 0, 'nothing is measured on the way out');
    vote.setTabHidden(ctl, false, sandbox.document);
    assert.equal(ctl.fits.length, 1, 'showing the tab refits first');
    assert.deepEqual(ctl.sent[1], ['tab.visible', true]);
    assert.equal(ctl._tabHidden, false);
});

test('a hidden component tab stays withdrawn when the browser tab comes back', () => {
    const sandbox = makeSandbox();
    const ctl = recordingController(sandbox);
    const vote = sandbox.TerminalSizeVote;
    vote.setTabHidden(ctl, true, sandbox.document);
    sandbox.document.visibilityState = 'hidden';
    vote.onVisibilityChange(ctl, sandbox.document);
    sandbox.document.visibilityState = 'visible';
    vote.onVisibilityChange(ctl, sandbox.document);
    assert.deepEqual(ctl.sent, [['tab.hidden', true], ['visibility.hidden', true]],
        'no rejoin while the component tab is still hidden');
});

test('showing a component tab inside a hidden browser tab does not rejoin', () => {
    const sandbox = makeSandbox();
    const ctl = recordingController(sandbox);
    const vote = sandbox.TerminalSizeVote;
    vote.setTabHidden(ctl, true, sandbox.document);
    sandbox.document.visibilityState = 'hidden';
    vote.setTabHidden(ctl, false, sandbox.document);
    assert.deepEqual(ctl.sent, [['tab.hidden', true]]);
    sandbox.document.visibilityState = 'visible';
    vote.onVisibilityChange(ctl, sandbox.document);
    assert.deepEqual(ctl.sent[1], ['visibility.visible', true], 'the browser tab coming back rejoins');
});

test('sendResize flags every frame from a client behind a hidden component tab', () => {
    const sandbox = makeSandbox();
    const P = realTerminalClass(sandbox);
    const frames = [];
    const self = resizeSelf(P, frames);
    self._tabHidden = true;
    self.sendResize('ResizeObserver', true);
    assert.deepEqual(frames[0], { type: 'pty_resize', cols: 82, rows: 30, hidden: true });
    self._tabHidden = false;
    self.sendResize('tab.visible', true);
    assert.deepEqual(frames[1], { type: 'pty_resize', cols: 82, rows: 30 },
        'a flag, never a faked size: the grid is the real one both times');
});
