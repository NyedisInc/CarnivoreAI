
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const BUFFER_SRC = read('client/js/terminal-input-buffer.js');
const TERM_SRC = read('client/js/terminal.js');
const INDEX_HTML = read('client/index.html');
const TERM_SINGLETON = '// THE CLASS ENDS ABOVE.';

function makeBuffer() {
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        Uint8Array, TextEncoder, TextDecoder, Promise, setTimeout, clearTimeout,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(BUFFER_SRC, sandbox, { filename: 'terminal-input-buffer.js' });
    if (!sandbox.window.TerminalInputBuffer) {
        throw new Error('terminal-input-buffer.js did not export itself');
    }
    return { window: sandbox.window, Buf: sandbox.window.TerminalInputBuffer };
}

const bytes = (n, fill) => new Uint8Array(n).fill(fill == null ? 65 : fill);

function fakeSocket(open = true) {
    return { readyState: open ? 1 : 3, sent: [], send(b) { this.sent.push(b); } };
}

function fakeController(ws) {
    return {
        ws: ws === undefined ? fakeSocket() : ws,
        _connGen: null,
        told: [],
        notes: 0,
        _showStatusPill(text) { this.told.push(text); },
        _noteUserInputToSession() { this.notes += 1; },
    };
}


test('with nothing armed, input goes straight through', () => {
    const { Buf } = makeBuffer();
    assert.equal(Buf.state(), 'idle');
    assert.equal(Buf.offer(null, bytes(4)), 'send_now');
    assert.equal(Buf.heldByteCount(), 0);
});

test('THE CASE THIS EXISTS FOR: input typed before ready is held, then delivered once, in order', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connectToSession');

    assert.equal(c.ws.readyState, 1, 'setup: the socket is open');
    assert.equal(Buf.send(c, bytes(2, 1)), false, 'held, not sent');
    assert.equal(Buf.send(c, bytes(3, 2)), false);
    assert.equal(c.ws.sent.length, 0, 'nothing may reach a pane that cannot hear');
    assert.equal(Buf.heldByteCount(), 5);

    const outcome = Buf.flushOnReady(c, { startup_command: 'none' });
    assert.equal(outcome, 'flushed');
    assert.equal(c.ws.sent.length, 2, 'delivered ONCE, not merged and not doubled');
    assert.equal(c.ws.sent[0][0], 1, 'and in the order it was typed');
    assert.equal(c.ws.sent[1][0], 2);
    assert.equal(Buf.heldByteCount(), 0);

    assert.equal(Buf.send(c, bytes(1, 3)), true);
    assert.equal(c.ws.sent.length, 3);
});

test('NO LOCAL ECHO: holding input writes nothing to the terminal', () => {
    const { Buf } = makeBuffer();
    const writes = [];
    const c = fakeController();
    c.term = { write: (d) => writes.push(d) };
    Buf.begin(c, 'connectToSession');
    Buf.send(c, bytes(8));
    assert.equal(writes.length, 0, 'the buffer must never paint');
});


test('the bound is 64 KiB of encoded input', () => {
    const { Buf } = makeBuffer();
    assert.equal(Buf.MAX_BUFFERED_BYTES, 64 * 1024);
});

test('OVERFLOW REJECTS THE WHOLE UNSENT BATCH, and says so exactly once', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connectToSession');

    Buf.send(c, bytes(32 * 1024, 1));
    Buf.send(c, bytes(32 * 1024, 2));
    assert.equal(Buf.heldByteCount(), 64 * 1024, 'setup: exactly at the bound');
    assert.equal(c.told.length, 0, 'nothing said while it still fits');

    assert.equal(Buf.send(c, bytes(1, 3)), false, 'the byte that overflows is not sent');
    assert.equal(Buf.heldByteCount(), 0, 'THE WHOLE BATCH GOES, not just the newest');
    assert.equal(Buf.state(), 'rejected_overflow');
    assert.equal(c.told.length, 1, 'and the user is told - a silent drop is the defect');
    assert.match(c.told[0], /type it again/);

    assert.equal(Buf.send(c, bytes(1, 4)), false);
    assert.equal(Buf.send(c, bytes(1, 5)), false);
    assert.equal(c.told.length, 1, 'said once, not once per keystroke');
    assert.equal(Buf.heldByteCount(), 0, 'and nothing is quietly re-accumulated');

    assert.equal(Buf.flushOnReady(c, {}), 'overflowed');
    assert.equal(c.ws.sent.length, 0);
    assert.equal(Buf.state(), 'ready', 'but the pane is still usable afterwards');
    assert.equal(Buf.send(c, bytes(1, 6)), true);
});

test('a poisoned generation recovers when a NEW connection begins', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'first');
    Buf.send(c, bytes(64 * 1024 + 1));
    assert.equal(Buf.state(), 'rejected_overflow');
    Buf.begin(c, 'second');
    assert.equal(Buf.state(), 'buffering', 'a new connection is a clean slate');
    assert.equal(Buf.send(c, bytes(4)), false, 'and it holds again');
    assert.equal(Buf.heldByteCount(), 4);
});


test('AN AMBIGUOUS DISCONNECT REPLAYS NOTHING', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connectToSession');
    Buf.send(c, bytes(6, 1));

    assert.equal(Buf.abandon(c, 'the socket closed'), 'discarded');
    assert.equal(Buf.heldByteCount(), 0);
    assert.equal(c.told.length, 1, 'the user is told their typing went');

    Buf.begin(c, 'reconnect');
    c.ws = fakeSocket();
    assert.equal(Buf.flushOnReady(c, {}), 'nothing_held');
    assert.equal(c.ws.sent.length, 0,
        'a replay onto the socket that replaced the one it was typed for '
        + 'is how a command gets run twice');
});

test('a close with nothing held says nothing', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connectToSession');
    assert.equal(Buf.abandon(c, 'closed'), 'nothing_held');
    assert.equal(c.told.length, 0, 'no pill for a disconnect that lost nothing');
});

test('input from a SUPERSEDED connection is dropped, silently', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    const genA = Buf.begin(c, 'session A');
    Buf.begin(c, 'session B');
    assert.notEqual(c._connGen, genA, 'a new connection is a new generation');

    assert.equal(Buf.offer(genA, bytes(4)), 'stale_generation');
    assert.equal(Buf.heldByteCount(), 0, "A's keystrokes must not join B's batch");
});

test('a ready for a superseded connection flushes nothing and opens nothing', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    const genA = Buf.begin(c, 'session A');
    Buf.begin(c, 'session B');
    Buf.send(c, bytes(5, 9));

    const r = Buf.release(genA);
    assert.equal(r.outcome, 'stale_generation');
    assert.equal(r.chunks.length, 0);
    assert.equal(Buf.state(), 'buffering',
        "a late ready for A must not un-hold B's input");
    assert.equal(Buf.heldByteCount(), 5);
});

test('A RECONNECT IS A NEW GENERATION, which a session id could not express', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    const first = Buf.begin(c, 'connect');
    Buf.send(c, bytes(3));
    Buf.abandon(c, 'socket dropped');
    const second = Buf.begin(c, 'reconnect to the SAME session');
    assert.notEqual(first, second);
    assert.equal(Buf.offer(first, bytes(3)), 'stale_generation');
});

test('the socket going between ready and the flush drops the batch rather than re-holding it', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connect');
    Buf.send(c, bytes(4));
    c.ws = fakeSocket(false);
    assert.equal(Buf.flushOnReady(c, {}), 'socket_gone');
    assert.equal(c.told.length, 1, 'and the user is told rather than left waiting');
    assert.equal(Buf.heldByteCount(), 0, 'nothing is carried into the next connection');
});


test('THE OTHER COMPATIBILITY DIRECTION: a server that never says ready must not leave the pane deaf', async () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connect');
    Buf.armReadyBackstop(c, 5);
    Buf.send(c, bytes(3, 1));
    Buf.send(c, bytes(4, 2));
    assert.equal(c.ws.sent.length, 0, 'held while the backstop is still running');

    await new Promise((r) => setTimeout(r, 25));
    assert.equal(c.ws.sent.length, 2,
        'DELIVERED, not dropped - the socket is open and the user typed '
        + 'these for this pane; the only thing missing was permission');
    assert.equal(c.told.length, 0, 'and nothing is reported, because nothing was lost');
    assert.equal(Buf.state(), 'ready',
        'and input passes straight through from here, exactly as every '
        + 'client behaved before the message existed');
    assert.equal(Buf.send(c, bytes(1, 3)), true);
});

test('a ready that DOES arrive cancels the backstop', async () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connect');
    Buf.armReadyBackstop(c, 5);
    Buf.send(c, bytes(3, 1));
    Buf.flushOnReady(c, { startup_command: 'none' });
    assert.equal(c.ws.sent.length, 1);
    await new Promise((r) => setTimeout(r, 25));
    assert.equal(c.ws.sent.length, 1, 'the timer must not fire a second flush');
});

test('a backstop cannot fire against a connection that has been superseded', async () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'session A');
    Buf.armReadyBackstop(c, 5);
    Buf.begin(c, 'session B');
    Buf.send(c, bytes(4, 2));
    await new Promise((r) => setTimeout(r, 25));
    assert.equal(c.ws.sent.length, 0, "A's timer must not flush B");
    assert.equal(Buf.state(), 'buffering');
});

test('a close cancels the backstop, so a dead socket is not written to', async () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connect');
    Buf.armReadyBackstop(c, 5);
    Buf.send(c, bytes(3));
    Buf.abandon(c, 'the socket closed');
    await new Promise((r) => setTimeout(r, 25));
    assert.equal(c.ws.sent.length, 0);
});

test('the backstop is generous against the handshake it is backing up', () => {
    const { Buf } = makeBuffer();
    assert.ok(Buf.READY_TIMEOUT_MS >= 4000,
        'tightening this turns a slow but healthy connect into lost keystrokes');
});

test('terminal.js arms the backstop when the socket OPENS', () => {
    const onopen = TERM_SRC.slice(TERM_SRC.indexOf('this.ws.onopen = '));
    assert.match(onopen.slice(0, 2500), /TerminalInputBuffer'?\)?\.armReadyBackstop\(this\)/,
        'armed from the socket opening, which is when the server owes us '
        + 'the message');
});


test('the seam sends through the socket only when the phase says so', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    assert.equal(Buf.send(c, bytes(2)), true);
    assert.equal(c.ws.sent.length, 1);
    Buf.begin(c, 'connect');
    assert.equal(Buf.send(c, bytes(2)), false);
    assert.equal(c.ws.sent.length, 1);
});

test('a closed socket with nothing armed reports failure rather than throwing', () => {
    const { Buf } = makeBuffer();
    const c = fakeController(fakeSocket(false));
    assert.equal(Buf.send(c, bytes(2)), false);
    assert.equal(Buf.send(fakeController(null), bytes(2)), false);
});

test('the flush notes user input exactly once, not once per chunk', () => {
    const { Buf } = makeBuffer();
    const c = fakeController();
    Buf.begin(c, 'connect');
    Buf.send(c, bytes(1, 1));
    Buf.send(c, bytes(1, 2));
    Buf.send(c, bytes(1, 3));
    Buf.flushOnReady(c, {});
    assert.equal(c.ws.sent.length, 3);
    assert.equal(c.notes, 1);
});

test('ONE message for every path that throws input away', () => {
    const { Buf } = makeBuffer();
    assert.equal(typeof Buf.RETYPE_MESSAGE, 'string');
    assert.match(Buf.RETYPE_MESSAGE, /^[a-z]/, 'UI copy is lowercase and plain');
    const copies = (BUFFER_SRC.match(/type it again/g) || []).length;
    assert.equal(copies, 1, `the retype wording appears ${copies} times`);
});


test('every keystroke-shaped path goes through the ONE seam', () => {
    const sandbox = { console: { log() {}, warn() {} } };
    sandbox.window = sandbox;
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    assert.notEqual(cut, -1, 'terminal.js no longer ends with its singleton line');
    const src = TERM_SRC.slice(0, cut);

    for (const site of [
        'this._sendUserBytes(new TextEncoder().encode(data))',
        'this._sendUserBytes(bytes)',
        'this._sendUserBytes(new TextEncoder().encode(keyData))',
    ]) {
        assert.ok(src.includes(site), `an input path stopped using the seam: ${site}`);
    }
    const ins = src.slice(src.indexOf('    insertText(text, ticket) {'));
    assert.ok(ins.slice(0, 1200).includes('this.term.paste(text)'),
        'insertText must paste through term.paste, not write the socket');

    const syn = src.slice(src.indexOf('_writeSynthetic(data) {'));
    assert.ok(syn.slice(0, 300).includes('this.ws.send(new TextEncoder().encode(data))'),
        'the app\'s own synthetic writes must not be buffered as user input');
});

test('terminal.js reacts to terminal.ready and nothing else opens the gate', () => {
    assert.ok(TERM_SRC.includes("type === 'terminal.ready'"),
        'the readiness message must have a branch, or the buffer never flushes');
    const calls = (TERM_SRC.match(/TerminalInputBuffer'?\)?\.flushOnReady/g) || []).length;
    assert.equal(calls, 1,
        `flushOnReady is called from ${calls} places - a second opener would `
        + 'let something other than the pane decide the pane can hear');
});

test('the socket close discards, and it is the only discard on that path', () => {
    const onclose = TERM_SRC.slice(TERM_SRC.indexOf('this.ws.onclose = '));
    const body = onclose.slice(0, 2000);
    assert.match(body, /TerminalInputBuffer'?\)?\.abandon\(this,/,
        'an ambiguous disconnect must throw the batch away');
    assert.ok(!/TerminalInputBuffer'?\)?\.release/.test(body),
        'a close must never flush - that is the replay this forbids');
});

test('index.html serves the buffer before terminal.js', () => {
    const order = [...INDEX_HTML.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)]
        .map((m) => m[1]);
    const buf = order.indexOf('terminal-input-buffer.js');
    assert.ok(buf >= 0, 'the module must be in index.html or it is dead code');
    assert.ok(buf < order.indexOf('terminal.js'));
});

test('COMPATIBILITY GATE: with the module absent, every path still sends', () => {
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        document: { getElementById: () => null },
        setTimeout, clearTimeout, Promise, TextEncoder, TextDecoder, Uint8Array,
        requestAnimationFrame: (fn) => { fn(); return 1; },
        WebSocket: { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
    };
    sandbox.window = sandbox;
    sandbox.window.document = sandbox.document;
    vm.createContext(sandbox);
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    vm.runInContext(TERM_SRC.slice(0, cut) + '\nwindow.__T = Terminal;',
        sandbox, { filename: 'terminal.js' });
    const P = sandbox.window.__T.prototype;

    assert.equal(sandbox.window.TerminalInputBuffer, undefined, 'setup: no module');
    const self = { ws: fakeSocket(), _connGen: null,
        _wiring: {}, _m: P._m,
        _sendUserBytes: P._sendUserBytes, _beginConnection: P._beginConnection };
    self._beginConnection('connect');
    assert.equal(self._connGen, null);
    assert.equal(self._sendUserBytes(bytes(3)), true,
        'with no buffer the bytes go straight out, exactly as they always did');
    assert.equal(self.ws.sent.length, 1);
});

test('NO EXTRACTION MAY MAKE A LOAD-ORDER ACCIDENT FATAL', async () => {
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        document: { getElementById: () => null },
        setTimeout, clearTimeout, Promise, TextEncoder, TextDecoder, Uint8Array,
        requestAnimationFrame: (fn) => { fn(); return 1; },
        WebSocket: { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
    };
    sandbox.window = sandbox;
    sandbox.window.document = sandbox.document;
    vm.createContext(sandbox);
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    vm.runInContext(TERM_SRC.slice(0, cut) + '\nwindow.__T = Terminal;',
        sandbox, { filename: 'terminal.js' });
    const P = sandbox.window.__T.prototype;
    assert.equal(sandbox.window.TerminalReadiness, undefined, 'setup: no module');

    sandbox.window.Terminal = function XtermTerminal() {};
    await P.waitForXterm.call({});

    sandbox.window.Terminal = sandbox.window.__T;
    await assert.rejects(() => P.waitForXterm.call({}), /xterm\.js did not load/);
});
