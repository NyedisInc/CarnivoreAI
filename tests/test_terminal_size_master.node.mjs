// ----------------------------------------------------------------------
// NO requestAnimationFrame (gotcha 9): the sandbox's rAF throws.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import { createRequire } from 'node:module';
import { TerminalProvider } from '../web/src/lib/terminal-provider/provider.ts';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const MASTER_SRC = read('client/js/terminal-size-master.js');
const VOTE_SRC = read('client/js/terminal-size-vote.js');
const METRICS_SRC = read('client/js/terminal-metrics.js');
const TERM_SRC = read('client/js/terminal.js');
const API_SRC = read('client/js/api.js') + read('client/js/api-session-lifecycle.js');
const INDEX_HTML = read('client/index.html');

globalThis.self = globalThis;
globalThis.window = globalThis;
globalThis.document = {
    createElement() {
        return { style: {}, classList: { add() {} }, setAttribute() {}, appendChild() {},
            addEventListener() {}, getContext() { return null; } };
    },
    addEventListener() {}, removeEventListener() {},
};
const { Terminal: XTerm } = createRequire(import.meta.url)(
    path.join(ROOT, 'client/vendor/xterm/xterm.js'));

const ME = 'tab-this-window-1';
const OTHER = 'tab-other-window';
const PANE = { cols: 120, rows: 30 };
const BOX = { cols: 80, rows: 24 };

function storage(broken = false) {
    const map = new Map();
    const fail = () => { throw new Error('storage refused'); };
    return {
        map,
        getItem: broken ? fail : (k) => (map.has(k) ? map.get(k) : null),
        setItem: broken ? fail : (k, v) => { map.set(k, String(v)); },
    };
}

function makeSandbox({ store = storage(), withMaster = true } = {}) {
    const events = [];
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout, clearTimeout, Date, Math, String, JSON, Number, Object, Array, Promise,
        Uint8Array,
        crypto: { randomUUID: () => ME },
        sessionStorage: store,
        document: {
            visibilityState: 'visible', addEventListener() {}, removeEventListener() {},
            querySelector() { return null; },
        },
        requestAnimationFrame() { throw new Error('no rAF (gotcha 9)'); },
        WebSocket: { OPEN: 1 },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
        dispatchEvent(event) { events.push(event); return true; },
        CloudeWeb: {
            calls: [],
            showTerminalSizeNotice(c, r) { this.calls.push(['show', c, r]); },
            clearTerminalSizeNotice() { this.calls.push(['clear']); },
        },
    };
    sandbox.window = sandbox;
    sandbox.events = events;
    sandbox.TerminalProvider = TerminalProvider;
    vm.createContext(sandbox);
    if (withMaster) vm.runInContext(MASTER_SRC, sandbox, { filename: 'terminal-size-master.js' });
    vm.runInContext(VOTE_SRC, sandbox, { filename: 'terminal-size-vote.js' });
    vm.runInContext(METRICS_SRC, sandbox, { filename: 'terminal-metrics.js' });
    return sandbox;
}

function client(sandbox, term) {
    const frames = [];
    const ctl = {
        term,
        frames,
        ws: { readyState: 1, send(text) { frames.push(JSON.parse(text)); } },
        _chrome: (name) => (name === 'statusText' ? {} : null),
        lastSentCols: BOX.cols,
        lastSentRows: BOX.rows,
    };
    sandbox.TerminalSizeVote.fitTo(ctl, BOX);
    return ctl;
}

/** A plain emulator stand-in with a styleable element. */
function stubTerm() {
    const attrs = new Map();
    return {
        cols: BOX.cols, rows: BOX.rows,
        resize(c, r) { this.cols = c; this.rows = r; },
        element: {
            style: {},
            setAttribute(k, v) { attrs.set(k, v); },
            hasAttribute(k) { return attrs.has(k); },
            getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
            removeAttribute(k) { attrs.delete(k); },
        },
    };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const write = (term, data) => new Promise((resolve) => term.write(data, resolve));

function paneBytes() {
    let out = '';
    for (let r = 1; r <= PANE.rows; r++) {
        const text = `row ${r} `.padEnd(PANE.cols - 1, String.fromCharCode(97 + (r % 26)));
        out += `\x1b[${r};1H\x1b[2K${text}|`;
    }
    for (let r = 2; r <= PANE.rows; r += 3) out += `\x1b[${r};5H\x1b[90GX`;
    return out;
}
function viewport(term) {
    const buf = term.buffer.active;
    const rows = [];
    for (let i = 0; i < term.rows; i++) rows.push(buf.getLine(buf.viewportY + i).translateToString(true));
    return rows;
}


test('clientId is minted once per tab and kept in sessionStorage', () => {
    const store = storage();
    const first = makeSandbox({ store }).TerminalSizeMaster.clientId();
    assert.equal(first, ME);
    assert.equal(store.map.get('carnivore.terminal.client_id'), ME);
    const again = makeSandbox({ store });
    again.crypto = { randomUUID: () => 'tab-would-be-new' };
    assert.equal(again.TerminalSizeMaster.clientId(), ME);
});

test('a malformed stored id is replaced, and refused storage still yields an id', () => {
    const store = storage();
    store.setItem('carnivore.terminal.client_id', '<bad>');
    assert.equal(makeSandbox({ store }).TerminalSizeMaster.clientId(), ME);
    const refused = makeSandbox({ store: storage(true) }).TerminalSizeMaster;
    assert.equal(refused.clientId(), ME);
    assert.equal(refused.clientId(), refused.clientId());
});

test('every primary terminal socket carries the id; an observer and /ws/events do not', () => {
    const at = API_SRC.indexOf("else if (path === '/ws/terminal' && window.TerminalSizeMaster)");
    assert.ok(at > 0, 'openWebSocket no longer adds client_id');
    assert.ok(API_SRC.indexOf("params.push('observer=1')") < at,
        'the id must be in the non-observer branch only');
    const order = [...INDEX_HTML.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)].map((m) => m[1]);
    assert.ok(order.indexOf('terminal-size-master.js') >= 0, 'not served: dead code');
    assert.ok(order.indexOf('terminal-size-master.js') < order.indexOf('terminal-size-vote.js'));
    assert.ok(TERM_SRC.includes("type === 'terminal_size' || type === 'size_master'"),
        'terminal.js no longer routes size_master frames');
});


test('a watcher smaller than the pane shows it ROW FOR ROW; the control garbles', async () => {
    const run = async (withMaster) => {
        const sandbox = makeSandbox({ withMaster });
        const term = new XTerm({ cols: BOX.cols, rows: BOX.rows, scrollback: 1000, allowProposedApi: true });
        const ctl = client(sandbox, term);
        sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: OTHER });
        sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'terminal_size', ...PANE, clients: 2 });
        const pane = new XTerm({ cols: PANE.cols, rows: PANE.rows, scrollback: 1000, allowProposedApi: true });
        const bytes = paneBytes();
        await write(pane, bytes);
        await write(term, bytes);
        return { shown: viewport(term), pane: viewport(pane), grid: [term.cols, term.rows] };
    };
    const follower = await run(true);
    assert.deepEqual(follower.grid, [PANE.cols, PANE.rows]);
    assert.deepEqual(follower.shown, follower.pane);
    const control = await run(false);
    assert.deepEqual(control.grid, [BOX.cols, BOX.rows], 'control: the #686 minimum');
    assert.notDeepEqual(control.shown, control.pane, 'control: a smaller grid must garble');
});

test('a smaller follower is scaled to its box; the scale lifts when the crown is released', () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox, stubTerm());
    const vote = sandbox.TerminalSizeVote;
    vote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: OTHER });
    vote.onTerminalSize(ctl, { type: 'terminal_size', ...PANE, clients: 2 });
    const expected = Math.min(BOX.cols / PANE.cols, BOX.rows / PANE.rows).toFixed(4);
    assert.equal(ctl.term.element.style.transform, `scale(${expected})`);
    assert.equal(ctl.term.element.style.transformOrigin, '0 0');
    vote.onTerminalSize(ctl, { type: 'terminal_size', ...BOX, clients: 2 });
    vote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: null });
    assert.equal(ctl.term.element.style.transform, '');
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BOX.cols, BOX.rows]);
});

test('#1050 a scaled follower maps the pointer to the cell under it, not the unscaled one', () => {
    const sandbox = makeSandbox();
    const term = stubTerm();
    const CELL = 10;
    const cellAt = (ev, el) => Math.floor((ev.clientX - el.getBoundingClientRect().left) / CELL);
    term._core = { _mouseService: { getCoords: cellAt, getMouseReportCoords: cellAt } };
    const screen = { getBoundingClientRect: () => ({ left: 100, top: 40 }) };
    const ctl = client(sandbox, term);
    const vote = sandbox.TerminalSizeVote;
    vote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: OTHER });
    vote.onTerminalSize(ctl, { type: 'terminal_size', ...PANE, clients: 2 });
    const scale = parseFloat(term.element.getAttribute('data-size-follower-scale'));
    assert.ok(scale < 1);
    const px = 100 + 20.5 * CELL * scale;
    assert.equal(term._core._mouseService.getCoords({ clientX: px, clientY: 40 }, screen), 20);
    assert.equal(term._core._mouseService.getMouseReportCoords({ clientX: px, clientY: 40 }, screen), 20);
    vote.onTerminalSize(ctl, { type: 'terminal_size', ...BOX, clients: 2 });
    vote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: null });
    assert.equal(term._core._mouseService.getCoords({ clientX: 150, clientY: 40 }, screen), 5);
});

test('the master itself is never scaled and keeps the #686 rule', () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox, stubTerm());
    const vote = sandbox.TerminalSizeVote;
    vote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: ME });
    vote.onTerminalSize(ctl, { type: 'terminal_size', ...PANE, clients: 2 });
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BOX.cols, BOX.rows]);
    assert.equal(ctl.term.element.style.transform, undefined);
});

test('a lone follower keeps the pane grid; a lone voter drops the limit as before', () => {
    const sandbox = makeSandbox();
    const vote = sandbox.TerminalSizeVote;
    const follower = client(sandbox, stubTerm());
    vote.onTerminalSize(follower, { type: 'size_master', session_id: 's', master: OTHER });
    vote.onTerminalSize(follower, { type: 'terminal_size', ...PANE, clients: 1 });
    assert.deepEqual([follower.term.cols, follower.term.rows], [PANE.cols, PANE.rows]);
    const voter = client(sandbox, stubTerm());
    vote.onTerminalSize(voter, { type: 'terminal_size', cols: 60, rows: 20, clients: 1 });
    assert.deepEqual([voter.term.cols, voter.term.rows], [BOX.cols, BOX.rows]);
});

test('a follower shows no size notice; a constrained voter still does', () => {
    const sandbox = makeSandbox();
    const vote = sandbox.TerminalSizeVote;
    const small = { type: 'terminal_size', cols: 60, rows: 20, clients: 2 };
    const voter = client(sandbox, stubTerm());
    vote.onTerminalSize(voter, small);
    assert.deepEqual(sandbox.CloudeWeb.calls.at(-1), ['show', 60, 20]);
    const follower = client(sandbox, stubTerm());
    vote.onTerminalSize(follower, { type: 'size_master', session_id: 's', master: OTHER });
    vote.onTerminalSize(follower, small);
    assert.deepEqual(sandbox.CloudeWeb.calls.at(-1), ['clear']);
});

test('a master CHANGE asks for one repaint; the attach greeting does not', async () => {
    const sandbox = makeSandbox();
    const vote = sandbox.TerminalSizeVote;
    const ctl = client(sandbox, stubTerm());
    vote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: null });
    await sleep(300);
    assert.deepEqual(ctl.frames, [], 'the greeting is not a change');
    vote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: ME });
    await sleep(300);
    assert.deepEqual(ctl.frames, [{ type: 'repaint' }]);
});

test('the crown hears every frame through one window event', () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox, stubTerm());
    sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'size_master', session_id: 's9', master: OTHER });
    const last = sandbox.events.at(-1);
    assert.equal(last.type, 'cloude:size-master');
    assert.deepEqual({ ...last.detail }, { sessionId: 's9', master: OTHER });
});

test('the width guard leaves a follower alone; it still trims a voter', () => {
    const sandbox = makeSandbox();
    const term = stubTerm();
    term._core = { _renderService: { dimensions: { css: { cell: { width: 10 } } } }, viewport: { scrollBarWidth: 0 } };
    term.options = { scrollback: 0 };
    term.element.parentElement = {};
    sandbox.getComputedStyle = () => ({ getPropertyValue: (k) => (k === 'width' ? '700px' : '0') });
    const ctl = client(sandbox, term);
    sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: OTHER });
    sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'terminal_size', ...PANE, clients: 2 });
    assert.equal(sandbox.TerminalMetrics.enforceWidthFit(ctl).reason, 'following');
    assert.equal(term.cols, PANE.cols);
    sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'size_master', session_id: 's', master: null });
    term.resize(80, 24);
    assert.equal(sandbox.TerminalMetrics.enforceWidthFit(ctl).reason, 'shrunk', 'control: a voter is trimmed');
});


test('an adopt sends nothing from a hidden tab, and a cell its OWN grid', () => {
    const sandbox = makeSandbox();
    const vote = sandbox.TerminalSizeVote;
    sandbox.TerminalMetrics.currentGrid = () => ({ cols: 191, rows: 54 });
    const cell = client(sandbox, stubTerm());
    assert.deepEqual({ ...vote.adoptGrid(cell, sandbox.document) }, { ...BOX }, 'a cell adopts with its own box');
    assert.deepEqual({ ...vote.adoptGrid(null, sandbox.document) }, { cols: 191, rows: 54 },
        'control: a page navigation still sends the page pane grid');
    sandbox.document.visibilityState = 'hidden';
    assert.deepEqual({ ...vote.adoptGrid(cell, sandbox.document) }, {}, 'a hidden browser tab has no say');
    assert.deepEqual({ ...vote.adoptGrid(null, sandbox.document) }, {});
    sandbox.document.visibilityState = 'visible';
    cell._tabHidden = true;
    assert.deepEqual({ ...vote.adoptGrid(cell, sandbox.document) }, {}, 'a hidden component tab has no say');
    assert.ok(API_SRC.includes('vote.adoptGrid(controller, document)'), 'api.js no longer asks adoptGrid');
    assert.ok(TERM_SRC.includes('window.API.adoptSession(tmuxName, true, this)'),
        'the re-adopt after a restart must pass its own client');
});
