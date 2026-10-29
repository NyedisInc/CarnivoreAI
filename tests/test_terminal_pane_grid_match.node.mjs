
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
const TERM_SRC = read('client/js/terminal.js');
const TERM_SINGLETON = '// THE CLASS ENDS ABOVE.';

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

const PANE = { cols: 160, rows: 47 };
const BOX = { cols: 163, rows: 49 };

function claudeStyleStream(rows, steps) {
    const H = rows;
    let model = new Array(H).fill('');
    const history = [];
    let out = '\x1b[2J\x1b[H';
    const render = (block) => {
        const room = H - block.length;
        const body = room > 0 ? history.slice(-room) : [];
        const want = new Array(Math.max(0, room - body.length)).fill('').concat(body, block);
        for (let r = 0; r < H; r++) {
            const a = want[r], b = model[r];
            let diff = '';
            for (let j = 0; j < Math.max(a.length, b.length); j++) {
                const x = j < a.length ? a[j] : ' ';
                const y = j < b.length ? b[j] : ' ';
                if (x !== y) diff += `\x1b[${j + 1}G${x}`;
            }
            if (diff) out += `\x1b[${r + 1};1H` + diff;
            model[r] = a;
        }
    };
    for (let n = 0; n < 50; n++) history.push(`static line ${n}`);
    for (let k = 0; k < steps; k++) {
        const h = 2 + (k % 4);
        const block = ['-'.repeat(130) + ' Stats -', `> prompt ${k} ${'y'.repeat(k % 40)}`];
        for (let r = 0; r < h; r++) {
            block.push(`  o general-purpose  task ${k}-${r} doing a thing   ${r}m . ${k}k tokens`);
        }
        block.push('  bypass permissions on');
        render(block);
        if (k % 5 === 4) {
            history.push(`agent finished ${k}`);
            out += `\x1b[${H};1H\n`;
            model = model.slice(1).concat(['']);
        }
    }
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

function makeSandbox() {
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout, clearTimeout, Date, Math, String, JSON,
        document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
        requestAnimationFrame() { throw new Error('no rAF (gotcha 9)'); },
        WebSocket: { OPEN: 1 },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(VOTE_SRC, sandbox, { filename: 'terminal-size-vote.js' });
    return sandbox;
}

function boxClient(sandbox) {
    const frames = [];
    const ctl = {
        term: new XTerm({ cols: BOX.cols, rows: BOX.rows, scrollback: 1000, allowProposedApi: true }),
        ws: { readyState: 1, send(text) { frames.push(JSON.parse(text)); } },
        frames,
    };
    if (sandbox.TerminalSizeVote.fitTo) sandbox.TerminalSizeVote.fitTo(ctl, BOX);
    return ctl;
}

const frame = (cols, rows, clients) => ({ type: 'terminal_size', cols, rows, clients });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('control: the Claude-style stream garbles a grid that does not match the pane', async () => {
    const stream = claudeStyleStream(PANE.rows, 200);
    const ref = new XTerm({ cols: PANE.cols, rows: PANE.rows, allowProposedApi: true });
    const big = new XTerm({ cols: BOX.cols, rows: BOX.rows, allowProposedApi: true });
    await write(ref, stream);
    await write(big, stream);
    const want = viewport(ref);
    const got = viewport(big).slice(0, PANE.rows);
    assert.notDeepEqual(got, want, 'the harness cannot tell a mismatched grid from a matched one');
});

test('a larger window held small shows exactly the pane, row for row', async () => {
    const sandbox = makeSandbox();
    const ctl = boxClient(sandbox);
    sandbox.TerminalSizeVote.onTerminalSize(ctl, frame(PANE.cols, PANE.rows, 2));
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [PANE.cols, PANE.rows],
        'the emulator must show the pane grid, not its own');

    const stream = claudeStyleStream(PANE.rows, 200);
    const ref = new XTerm({ cols: PANE.cols, rows: PANE.rows, allowProposedApi: true });
    await write(ref, stream);
    await write(ctl.term, stream);
    assert.deepEqual(viewport(ctl.term), viewport(ref));
});

test('the vote stays the fitted box while the screen shows the pane', () => {
    const sandbox = makeSandbox();
    const ctl = boxClient(sandbox);
    sandbox.TerminalSizeVote.onTerminalSize(ctl, frame(PANE.cols, PANE.rows, 2));
    assert.deepEqual({ ...sandbox.TerminalSizeVote.voteGrid(ctl) }, BOX);

    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    assert.notEqual(cut, -1, 'terminal.js no longer carries its class-end marker');
    vm.runInContext(TERM_SRC.slice(0, cut) + '\nwindow.__T = Terminal;', sandbox,
        { filename: 'terminal.js' });
    const P = sandbox.__T.prototype;
    const sent = [];
    const self = Object.assign(ctl, {
        ws: { readyState: 1, send(text) { sent.push(JSON.parse(text)); } },
        lastSentCols: null, lastSentRows: null, _wiring: {}, _m: P._m,
    });
    P.sendResize.call(self, 'window.resize', true);
    assert.deepEqual(sent[0], { type: 'pty_resize', cols: BOX.cols, rows: BOX.rows },
        'voting the forced grid would stop the minimum ever growing back');
});

test('the limit lifting returns to the box; one client means no limit', () => {
    const sandbox = makeSandbox();
    const ctl = boxClient(sandbox);
    const V = sandbox.TerminalSizeVote;
    V.onTerminalSize(ctl, frame(PANE.cols, PANE.rows, 2));
    V.onTerminalSize(ctl, frame(BOX.cols, BOX.rows, 2));
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BOX.cols, BOX.rows]);
    V.onTerminalSize(ctl, frame(PANE.cols, PANE.rows, 2));
    V.onTerminalSize(ctl, frame(PANE.cols, PANE.rows, 1));
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BOX.cols, BOX.rows],
        'a lone client is the pane; a stale limit must not hold it small');
});

test('never larger than the box, and a refit under a limit is one resize', () => {
    const sandbox = makeSandbox();
    const ctl = boxClient(sandbox);
    const V = sandbox.TerminalSizeVote;
    V.onTerminalSize(ctl, frame(200, 30, 2));
    assert.deepEqual([ctl.term.cols, ctl.term.rows], [BOX.cols, 30]);
    const sizes = [];
    ctl.term.onResize((e) => sizes.push([e.cols, e.rows]));
    V.fitTo(ctl, { cols: BOX.cols, rows: 60 });
    assert.deepEqual(sizes, [], 'the grid on screen did not change, so nothing resizes');
    V.fitTo(ctl, { cols: 120, rows: 60 });
    assert.deepEqual(sizes, [[120, 30]], 'straight to the allowed grid, never via the box');
    assert.deepEqual({ ...V.voteGrid(ctl) }, { cols: 120, rows: 60 });
});

test('a grid change asks for ONE repaint on the socket that saw it; a switch cancels', async () => {
    const sandbox = makeSandbox();
    const ctl = boxClient(sandbox);
    const V = sandbox.TerminalSizeVote;
    V.onTerminalSize(ctl, frame(PANE.cols, PANE.rows, 2));
    V.onTerminalSize(ctl, frame(PANE.cols - 1, PANE.rows, 2));
    V.onTerminalSize(ctl, frame(PANE.cols - 1, PANE.rows, 2));
    await sleep(400);
    assert.deepEqual(ctl.frames, [{ type: 'repaint' }]);

    V.onTerminalSize(ctl, frame(PANE.cols, PANE.rows, 2));
    V.clear(ctl);
    await sleep(400);
    assert.equal(ctl.frames.length, 1, 'a session switch drops the pending repaint');

    V.onTerminalSize(ctl, frame(PANE.cols - 2, PANE.rows, 2));
    ctl.ws = { readyState: 1, send() { throw new Error('a newer socket must not be asked'); } };
    await sleep(400);
    assert.equal(ctl.frames.length, 1);
});
