
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import { createRequire } from 'node:module';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
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

const PANE = { cols: 81, rows: 25 };

const SHRINK = [];
for (let c = PANE.cols - 4; c >= 9; c -= 4) SHRINK.push(c);

function frameBytes(k) {
    let out = '';
    for (let r = 1; r <= PANE.rows; r++) {
        out += `\x1b[${r};1H\x1b[2Kline ${r} frame ${k} ${'still thinking with max effort'.slice(0, 20 + (r % 10))}`;
    }
    return out;
}
function diffBytes(k) {
    let out = '';
    for (let r = 1; r <= PANE.rows; r += 2) out += `\x1b[${r};7H\x1b[13G${k % 10}`;
    return out;
}

function write(term, data) {
    return new Promise((resolve) => term.write(data, resolve));
}
function viewport(term) {
    const buf = term.buffer.active;
    const rows = [];
    for (let i = 0; i < term.rows; i++) {
        const line = buf.getLine(buf.viewportY + i);
        rows.push(line ? line.translateToString(true) : '');
    }
    return rows;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function makeSandbox() {
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout, clearTimeout, Date, Math, String, JSON, Number, Object, Array, Promise,
        document: {
            visibilityState: 'visible', addEventListener() {}, removeEventListener() {},
            querySelector() { return null; },
        },
        requestAnimationFrame() { throw new Error('no rAF (gotcha 9)'); },
        WebSocket: { OPEN: 1 },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(VOTE_SRC, sandbox, { filename: 'terminal-size-vote.js' });
    vm.runInContext(METRICS_SRC, sandbox, { filename: 'terminal-metrics.js' });
    return sandbox;
}

function client(sandbox) {
    const frames = [];
    const sent = [];
    const ctl = {
        term: new XTerm({ cols: PANE.cols, rows: PANE.rows, scrollback: 1000, allowProposedApi: true }),
        ws: { readyState: 1, send(text) { frames.push(JSON.parse(text)); } },
        box: { ...PANE },
        proposals: 0,
        frames, sent,
        sendResize(reason, force) { sent.push([reason, force]); },
    };
    ctl.fitAddon = {
        proposeDimensions() { ctl.proposals += 1; return { ...ctl.box }; },
        fit() { throw new Error('the raw fit must never run'); },
    };
    sandbox.TerminalSizeVote.fitTo(ctl, PANE);
    return ctl;
}

async function parkAndReturn(sandbox, ctl, freeze) {
    const V = sandbox.TerminalSizeVote;
    const M = sandbox.TerminalMetrics;
    const widths = [];
    if (freeze) V.setTabHidden(ctl, true, sandbox.document);
    for (const [i, cols] of SHRINK.entries()) {
        ctl.box = { cols, rows: PANE.rows };
        M.guardedFit(ctl);
        widths.push(ctl.term.cols);
        await write(ctl.term, diffBytes(i));
    }
    ctl.box = { ...PANE };
    if (freeze) V.setTabHidden(ctl, false, sandbox.document);
    else M.guardedFit(ctl);
    return widths;
}

test('control: a shelf refit that reflows the emulator leaves it unlike the pane', async () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox);
    const ref = new XTerm({ cols: PANE.cols, rows: PANE.rows, allowProposedApi: true });
    await write(ref, frameBytes(0));
    await write(ctl.term, frameBytes(0));
    const widths = await parkAndReturn(sandbox, ctl, false);
    assert.equal(Math.min(...widths), 9, 'setup: the unfrozen emulator follows the shelf down');
    for (let i = 0; i < SHRINK.length; i++) await write(ref, diffBytes(i));
    await write(ref, diffBytes(99));
    await write(ctl.term, diffBytes(99));
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [PANE.cols, PANE.rows]);
    assert.notDeepEqual(viewport(ctl.term), viewport(ref),
        'the harness cannot tell a reflowed buffer from a clean one');
});

test('a parked terminal never resizes, and matches the pane row for row on return', async () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox);
    const ref = new XTerm({ cols: PANE.cols, rows: PANE.rows, allowProposedApi: true });
    await write(ref, frameBytes(0));
    await write(ctl.term, frameBytes(0));
    const widths = await parkAndReturn(sandbox, ctl, true);
    assert.deepEqual(widths, SHRINK.map(() => PANE.cols), 'no column may drop while parked');
    assert.equal(ctl.proposals, 1, 'nothing is even measured while parked; the return measures once');
    for (let i = 0; i < SHRINK.length; i++) await write(ref, diffBytes(i));
    await write(ref, diffBytes(99));
    await write(ctl.term, diffBytes(99));
    assert.deepEqual(viewport(ctl.term), viewport(ref));
});

test('the return rejoins the vote and asks for exactly ONE repaint', async () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox);
    const V = sandbox.TerminalSizeVote;
    V.setTabHidden(ctl, true, sandbox.document);
    V.onTerminalSize(ctl, { type: 'terminal_size', cols: 70, rows: 20, clients: 2 });
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [70, 20],
        'a pane grid frame while parked is shown at once (scrollback scatter)');
    V.setTabHidden(ctl, false, sandbox.document);
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [70, 20], 'the rejoin keeps the pane grid');
    V.onTerminalSize(ctl, { type: 'terminal_size', cols: 70, rows: 20, clients: 2 });
    await sleep(400);
    assert.deepEqual(ctl.frames, [{ type: 'repaint' }]);
    assert.deepEqual(ctl.sent, [['tab.hidden', true], ['tab.visible', true]]);

    V.setTabHidden(ctl, false, sandbox.document);
    await sleep(400);
    assert.equal(ctl.frames.length, 1, 'a tab that was never hidden asks for nothing');
});

test('a return that happens while the browser tab is hidden repaints on the visible rejoin', async () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox);
    const V = sandbox.TerminalSizeVote;
    V.setTabHidden(ctl, true, sandbox.document);
    sandbox.document.visibilityState = 'hidden';
    V.setTabHidden(ctl, false, sandbox.document);
    await sleep(400);
    assert.deepEqual(ctl.frames, [], 'no repaint while nobody can see it');
    sandbox.document.visibilityState = 'visible';
    V.onVisibilityChange(ctl, sandbox.document);
    await sleep(400);
    assert.deepEqual(ctl.frames, [{ type: 'repaint' }]);
});

test('guardedFit refuses a withdrawn client as `withdrawn`, and terminal-layout does not retry it', () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox);
    ctl._tabHidden = true;
    assert.deepEqual({ ...sandbox.TerminalMetrics.guardedFit(ctl) }, { fitted: false, reason: 'withdrawn' });
    const layout = read('client/js/terminal-layout.js');
    assert.match(layout, /result\.reason === 'withdrawn'\) return;/);
});

test('a parked terminal shows the pane grid, so a resized pane never scatters its scrollback', async () => {
    const sandbox = makeSandbox();
    const ctl = client(sandbox);
    const V = sandbox.TerminalSizeVote;
    V.setTabHidden(ctl, true, sandbox.document);
    V.onTerminalSize(ctl, { type: 'terminal_size', cols: 120, rows: PANE.rows, clients: 2 });
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [120, PANE.rows],
        'the parked emulator must be at the pane grid while bytes keep arriving');
    const words = 'would open Google, and then the callback would die trying to swap the code without the secret, and then'.split(' ');
    let bytes = '';
    for (let line = 0; line < 60; line++) {
        let col = 3;
        for (const w of words) { bytes += `\x1b[${col}G${w}`; col += w.length + 1; }
        bytes += '\r\n';
    }
    await write(ctl.term, bytes);
    const buf = ctl.term.buffer.active;
    const row = buf.getLine(0).translateToString(true);
    assert.equal(row.trim(), words.join(' '), 'a scrolled-off line must read as one line');
});
