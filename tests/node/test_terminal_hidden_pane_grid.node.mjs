// ----------------------------------------------------------------------
// NO requestAnimationFrame (gotcha 9): the sandbox's rAF throws.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import { createRequire } from 'node:module';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const MASTER_SRC = read('client/js/terminal-size-master.js');
const VOTE_SRC = read('client/js/terminal-size-vote.js');
const METRICS_SRC = read('client/js/terminal-metrics.js');

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

const PANE = { cols: 100, rows: 39 };
const BOX = { cols: 105, rows: 40 };
const BIG = { cols: 160, rows: 61 };

function makeSandbox(visibility) {
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout, clearTimeout, Date, Math, String, JSON, Number, Object, Array, Promise,
        Uint8Array,
        crypto: { randomUUID: () => 'tab-this-window' },
        sessionStorage: { getItem: () => null, setItem() {} },
        document: {
            visibilityState: visibility, addEventListener() {}, removeEventListener() {},
            querySelector() { return null; },
        },
        requestAnimationFrame() { throw new Error('no rAF (gotcha 9)'); },
        WebSocket: { OPEN: 1 },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
        dispatchEvent() { return true; },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(MASTER_SRC, sandbox, { filename: 'terminal-size-master.js' });
    vm.runInContext(VOTE_SRC, sandbox, { filename: 'terminal-size-vote.js' });
    vm.runInContext(METRICS_SRC, sandbox, { filename: 'terminal-metrics.js' });
    return sandbox;
}

function client(sandbox, term, box = BOX) {
    const frames = [];
    const ctl = {
        term,
        frames,
        ws: { readyState: 1, send(text) { frames.push(JSON.parse(text)); } },
        _chrome: () => null,
        sendResize(reason, force) { frames.push({ type: 'pty_resize', reason, force }); },
    };
    sandbox.TerminalSizeVote.fitTo(ctl, box);
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
            removeAttribute(k) { attrs.delete(k); },
        },
    };
}

const write = (term, data) => new Promise((resolve) => term.write(data, resolve));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function paneBytes() {
    let out = '\x1b[H\x1b[2J';
    for (let r = 0; r < PANE.rows - 1; r++) {
        out += `r${r} `.padEnd(PANE.cols, String.fromCharCode(97 + (r % 26)));
    }
    out += '\x1b[3;96Hgent\x1b[4;95Haily\x1b[5;93Hriefing';
    out += `\x1b[${PANE.rows};1Hstatus line\n`;
    return out;
}

function viewport(term) {
    const buf = term.buffer.active;
    const rows = [];
    for (let i = 0; i < term.rows; i++) rows.push(buf.getLine(buf.viewportY + i).translateToString(true));
    return rows;
}

test('a lone hidden tab shows the pane it did not choose ROW FOR ROW; the control garbles', async () => {
    const run = async (visibility) => {
        const sandbox = makeSandbox(visibility);
        const term = new XTerm({ cols: BOX.cols, rows: BOX.rows, scrollback: 1000, allowProposedApi: true });
        const ctl = client(sandbox, term);
        sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'terminal_size', ...PANE, clients: 1 });
        const pane = new XTerm({ cols: PANE.cols, rows: PANE.rows, scrollback: 1000, allowProposedApi: true });
        const bytes = paneBytes();
        await write(pane, bytes);
        await write(term, bytes);
        return { shown: viewport(term), pane: viewport(pane), grid: [term.cols, term.rows] };
    };
    const hidden = await run('hidden');
    assert.deepEqual(hidden.grid, [PANE.cols, PANE.rows], 'the hidden tab kept its own box');
    assert.deepEqual(hidden.shown, hidden.pane);
    const control = await run('visible');
    assert.deepEqual(control.grid, [BOX.cols, BOX.rows]);
    assert.notDeepEqual(control.shown, control.pane, 'control: a wrong grid must garble');
});

test('a hidden tab shows a pane LARGER than its box exactly, scaled to fit', () => {
    const sandbox = makeSandbox('hidden');
    const ctl = client(sandbox, stubTerm());
    sandbox.TerminalSizeVote.onTerminalSize(ctl, { type: 'terminal_size', ...BIG, clients: 2 });
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BIG.cols, BIG.rows]);
    const scale = Math.min(BOX.cols / BIG.cols, BOX.rows / BIG.rows).toFixed(4);
    assert.equal(ctl.term.element.style.transform, `scale(${scale})`);
});

test('coming back visible returns to the box, unscaled, and asks for one repaint', async () => {
    const sandbox = makeSandbox('hidden');
    const ctl = client(sandbox, stubTerm());
    const vote = sandbox.TerminalSizeVote;
    vote.onTerminalSize(ctl, { type: 'terminal_size', ...BIG, clients: 2 });
    sandbox.document.visibilityState = 'visible';
    vote.onVisibilityChange(ctl, sandbox.document);
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BOX.cols, BOX.rows]);
    assert.equal(ctl.term.element.style.transform, '');
    assert.ok(ctl.frames.some((f) => f.type === 'pty_resize' && f.reason === 'visibility.visible'));
    await sleep(300);
    assert.equal(ctl.frames.filter((f) => f.type === 'repaint').length, 1);
});

test('a lone voter that goes hidden never shows a grid the pane has since left', () => {
    const sandbox = makeSandbox('visible');
    const ctl = client(sandbox, stubTerm());
    const vote = sandbox.TerminalSizeVote;
    vote.onTerminalSize(ctl, { type: 'terminal_size', ...PANE, clients: 1 });
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BOX.cols, BOX.rows]);
    vote.fitTo(ctl, BIG);
    sandbox.document.visibilityState = 'hidden';
    vote.fitTo(ctl, BIG);
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BIG.cols, BIG.rows]);
});
