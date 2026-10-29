
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

function makeGate() {
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        Uint8Array, TextEncoder, TextDecoder, Promise, setTimeout, clearTimeout,
        atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const f of ['terminal-write-queue.js', 'terminal-scrollback-paint.js', 'terminal-history-gate.js']) {
        vm.runInContext(read('client/js/' + f), sandbox, { filename: f });
    }
    assert.ok(sandbox.TerminalHistoryGate, 'terminal-history-gate.js did not export itself');
    return { Gate: sandbox.TerminalHistoryGate, sandbox };
}

function deferred() {
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    return { promise, resolve };
}

const b64Of = (text) => Buffer.from(text, 'binary').toString('base64');

function fakeController(Gate) {
    const writes = [];
    const ctl = {
        _connGen: 7,
        navCurrent: true,
        term: { write(b) { writes.push(typeof b === 'string' ? b : Buffer.from(b).toString('binary')); } },
        _navCurrent() { return this.navCurrent; },
        enqueue(bytes) {
            if (Gate.offer(this, bytes)) return;
            writes.push(Buffer.from(bytes).toString('binary'));
        },
    };
    return { ctl, writes };
}

const frame = (s) => new Uint8Array(Buffer.from(s, 'binary'));
const tick = () => new Promise((r) => setImmediate(r));
const RESET = '\x1b[?1049l\x1b[2J\x1b[H';

test('history lands before any live byte; frames held mid-history are neither lost nor reordered', async () => {
    const { Gate } = makeGate();
    const { ctl, writes } = fakeController(Gate);
    const hist = deferred();
    Gate.begin(ctl, hist.promise);
    assert.equal(Gate.holding(ctl), true);
    ctl.enqueue(frame('A'));
    ctl.enqueue(frame('B'));
    assert.deepEqual(writes, [], 'nothing reaches the terminal while the history is pending');
    hist.resolve(b64Of('HISTORY'));
    await tick();
    ctl.enqueue(frame('C'));
    assert.deepEqual(writes, [RESET, 'HISTORY', 'A', 'B', 'C']);
    assert.equal(Gate.holding(ctl), false);
});

test('a capture that resolves after the bound fired is never written', async () => {
    const { Gate } = makeGate();
    const { ctl, writes } = fakeController(Gate);
    const hist = deferred();
    Gate.begin(ctl, hist.promise);
    ctl.enqueue(frame('A'));
    Gate.release(ctl, 'bound');
    ctl.enqueue(frame('B'));
    hist.resolve(b64Of('LATE'));
    await tick();
    assert.deepEqual(writes, ['A', 'B'], 'live frames flowed; the late history stayed out');
});

test('the real bound timer releases the frames and drops the late capture', async () => {
    const { Gate } = makeGate();
    const { ctl, writes } = fakeController(Gate);
    const hist = deferred();
    Gate.begin(ctl, hist.promise, { holdMs: 1 });
    ctl.enqueue(frame('A'));
    await new Promise((r) => setTimeout(r, 25));
    assert.deepEqual(writes, ['A']);
    hist.resolve(b64Of('LATE'));
    await tick();
    assert.deepEqual(writes, ['A']);
});

test('a capture for an older connection generation or a stale navigation is dropped', async () => {
    for (const mutate of [(c) => { c._connGen = 8; }, (c) => { c.navCurrent = false; }]) {
        const { Gate } = makeGate();
        const { ctl, writes } = fakeController(Gate);
        const hist = deferred();
        Gate.begin(ctl, hist.promise);
        ctl.enqueue(frame('A'));
        mutate(ctl);
        hist.resolve(b64Of('STALE'));
        await tick();
        assert.ok(!writes.includes('STALE'), 'a stale capture must not be written');
        assert.ok(!writes.includes('A'), 'frames held for a superseded connection are not replayed');
        assert.equal(Gate.holding(ctl), false);
    }
});

test('a switch mid-load discards the held frames and the late capture', async () => {
    const { Gate } = makeGate();
    const { ctl, writes } = fakeController(Gate);
    const hist = deferred();
    Gate.begin(ctl, hist.promise);
    ctl.enqueue(frame('A'));
    Gate.discard(ctl, 'a new connection begins');
    hist.resolve(b64Of('OLD'));
    await tick();
    ctl.enqueue(frame('NEW'));
    assert.deepEqual(writes, ['NEW']);
});

test('a null capture releases the hold: live frames flow, nothing throws', async () => {
    const { Gate } = makeGate();
    const { ctl, writes } = fakeController(Gate);
    Gate.begin(ctl, Promise.resolve(null));
    ctl.enqueue(frame('A'));
    await tick();
    assert.deepEqual(writes, ['A']);
    const second = fakeController(Gate);
    Gate.begin(second.ctl, Promise.reject(new Error('boom')));
    second.ctl.enqueue(frame('B'));
    await tick();
    assert.deepEqual(second.writes, ['B']);
});

test('the hold is 64 KiB: the cap sheds the OLDEST whole frames and announces it', async () => {
    const { Gate } = makeGate();
    assert.equal(Gate.HELD_MAX_BYTES, 64 * 1024);
    const { ctl, writes } = fakeController(Gate);
    const hist = deferred();
    Gate.begin(ctl, hist.promise);
    const big = (ch) => frame(ch.repeat(30 * 1024));
    ctl.enqueue(big('A'));
    ctl.enqueue(big('B'));
    ctl.enqueue(big('C'));
    hist.resolve(null);
    await tick();
    assert.match(writes[0], /dropped \d+ bytes/, 'the shed is announced first');
    assert.ok(!writes.some((w) => w[0] === 'A' && w.length > 100), 'the oldest frame went');
    assert.equal(writes[writes.length - 1][0], 'C', 'the newest frame survived');
    assert.equal(writes.slice(1).join('').length <= 64 * 1024, true);
});

test('the input buffer is untouched: still 64 KiB and still keyed by connection generation', () => {
    const src = read('client/js/terminal-input-buffer.js');
    assert.match(src, /var MAX_BUFFERED_BYTES = 64 \* 1024;/);
    assert.match(src, /controller\._connGen = gen/);
});

test('terminal.js and index.html are wired: offer in enqueue, discard on a new connection, release on close', () => {
    const term = read('client/js/terminal.js');
    assert.match(term, /enqueue\(bytes\) \{\n\s+if \(window\.TerminalHistoryGate && window\.TerminalHistoryGate\.offer\(this, bytes\)\) return;/);
    assert.match(term, /TerminalHistoryGate\.discard\(this, 'a new connection begins'\)/);
    assert.match(term, /TerminalHistoryGate\.release\(this, 'the socket closed'\)/);
    assert.match(term, /TerminalHistoryGate\.begin\(this, session\.initial_scrollback_pending\)/);
    const html = read('client/index.html');
    const order = (n) => html.indexOf('/static/js/' + n);
    assert.ok(order('terminal-history-gate.js') > order('terminal-scrollback-paint.js'));
    assert.ok(order('terminal-history-gate.js') < order('terminal.js'));
});


function makeApi() {
    const calls = [];
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, info() {}, error() {} },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        URL,
        location: { protocol: 'http:', host: 'x.test' },
        document: { baseURI: 'http://x.test/' },
        fetch(u) {
            const d = deferred();
            calls.push({ url: String(u), answer: (body) => d.resolve({
                ok: true, status: 200, headers: { get: () => 'application/json' },
                json: async () => body, text: async () => JSON.stringify(body),
            }) });
            return d.promise;
        },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(read('client/js/api.js'), sandbox, { filename: 'api.js' });
    return { api: sandbox.window.API, calls };
}

test('api.getSession parallelHistory: two requests, info resolves while the capture is pending', async () => {
    const { api, calls } = makeApi();
    const p = api.getSession('ses_1', { includeScrollback: true, parallelHistory: true, cols: 80, rows: 24 });
    await tick();
    assert.equal(calls.length, 2);
    assert.match(calls[0].url, /include_scrollback=1/, 'the capture request is fired first');
    assert.ok(!/include_scrollback/.test(calls[1].url), 'the info request carries no capture');
    calls[1].answer({ session: { id: 'ses_1' } });
    const info = await p;
    assert.equal(info.session.id, 'ses_1');
    assert.equal(Object.keys(info).includes('initial_scrollback_pending'), false, 'non-enumerable');
    assert.ok(!JSON.stringify(info).includes('pending'));
    let settled = false;
    info.initial_scrollback_pending.then(() => { settled = true; });
    await tick();
    assert.equal(settled, false, 'the capture is still pending');
    calls[0].answer({ session: { id: 'ses_1' }, initial_scrollback_b64: 'QUJD' });
    assert.equal(await info.initial_scrollback_pending, 'QUJD');
});

test('api.getSession without the flag is wire-identical: one request, no pending property', async () => {
    const { api, calls } = makeApi();
    const p = api.getSession('ses_1', { includeScrollback: true });
    await tick();
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /include_scrollback=1/);
    calls[0].answer({ session: { id: 'ses_1' }, initial_scrollback_b64: 'QUJD' });
    const info = await p;
    assert.equal(info.initial_scrollback_b64, 'QUJD');
    assert.equal('initial_scrollback_pending' in info, false);
});
