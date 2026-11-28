
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const b64Of = (t) => Buffer.from(t, 'binary').toString('base64');
const tick = () => new Promise((r) => setImmediate(r));

function make(script, retryOverride) {
    const timers = [];
    const win = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        Uint8Array, TextEncoder, TextDecoder, Promise, clearTimeout,
        setTimeout: (fn, ms) => { if (ms <= 1) return setTimeout(fn, ms); if (ms >= 99999) return 0; timers.push({ fn, ms }); return timers.length; },
        atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    };
    win.window = win;
    vm.createContext(win);
    const calls = [];
    win.TerminalHistory = { async ensureLoaded(term, sid, ctl, opts) { calls.push({ sid, opts }); return script(calls.length); } };
    for (const f of ['terminal-write-queue.js', 'terminal-scrollback-paint.js', 'terminal-history-gate.js', 'terminal-history-followup.js']) {
        vm.runInContext(read('client/js/' + f), win, { filename: f });
    }
    const ctl = {
        _connGen: 3, _navToken: 9, _disposed: false, term: {}, ws: { readyState: 1 },
        _sessionId() { return 'ses_1'; }, _navCurrent() { return true; },
        enqueue() {},
    };
    return { Gate: win.TerminalHistoryGate, ctl, calls, timers };
}

test('a capture after the bound is handed to ensureLoaded with its own bytes, no second request', async () => {
    const { Gate, ctl, calls } = make(() => ({ loaded: 'painted', lines: 5 }));
    let resolve; const p = new Promise((r) => { resolve = r; });
    Gate.begin(ctl, p, { holdMs: 1 });
    await new Promise((r) => setTimeout(r, 20));
    assert.equal(calls.length, 0);
    resolve(b64Of('LATE'));
    await tick();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].opts.capturedB64, b64Of('LATE'));
    assert.equal(calls[0].sid, 'ses_1');
});

test('a stale navigation, an older connection, a closed socket or teardown never paint', async () => {
    const muts = [(c) => { c._navToken = 10; }, (c) => { c._connGen = 4; },
        (c) => { c._navCurrent = () => false; }, (c) => { c._disposed = true; }];
    for (const mutate of muts) {
        const { Gate, ctl, calls } = make(() => ({ loaded: 'painted' }));
        let resolve; const p = new Promise((r) => { resolve = r; });
        Gate.begin(ctl, p, { holdMs: 1 });
        await new Promise((r) => setTimeout(r, 20));
        mutate(ctl);
        resolve(b64Of('LATE'));
        await tick();
        assert.equal(calls.length, 0);
    }
});

test('failed requests retry at most 3 times on a timer and a switch stops them', async () => {
    const { Gate, ctl, calls, timers } = make(() => ({ loaded: 'unavailable', reason: 'request_failed' }));
    Gate.begin(ctl, Promise.resolve(null), { holdMs: 99999 });
    await tick(); await tick();
    assert.equal(calls.length, 1, 'null inside the bound probes once');
    for (let i = 0; i < 6 && timers.length; i++) { timers.shift().fn(); await tick(); await tick(); }
    assert.equal(calls.length, 3, 'bounded at three attempts');
    assert.equal(timers.length, 0, 'no timer left after giving up');

    const b = make(() => ({ loaded: 'unavailable', reason: 'request_failed' }));
    b.Gate.begin(b.ctl, Promise.resolve(null), { holdMs: 99999 });
    await tick(); await tick();
    assert.equal(b.timers.length, 1);
    b.ctl._navToken = 10; // session switch
    b.timers.shift().fn(); await tick();
    assert.equal(b.calls.length, 1, 'a switch stops the retry');
});

test('a capture that does not exist is probed once and not retried', async () => {
    const { Gate, ctl, calls, timers } = make(() => ({ loaded: 'unavailable', reason: 'no_capture' }));
    Gate.begin(ctl, Promise.resolve(null), { holdMs: 99999 });
    await tick(); await tick();
    assert.equal(calls.length, 1);
    assert.equal(timers.length, 0);
});

test('a socket that closes the way terminal.js does (ws = null) stops the retry; a different ws does too', async () => {
    for (const mutate of [(c) => { c.ws = null; }, (c) => { c.ws = { readyState: 1 }; }]) {
        const b = make(() => ({ loaded: 'unavailable', reason: 'request_failed' }));
        b.Gate.begin(b.ctl, Promise.resolve(null), { holdMs: 99999 });
        await tick(); await tick();
        assert.equal(b.timers.length, 1);
        mutate(b.ctl);
        b.timers.shift().fn(); await tick();
        assert.equal(b.calls.length, 1);
    }
});

test('stillValid is passed to ensureLoaded and goes false on a switch; refusals other than request_failed are final', async () => {
    const b = make(() => ({ loaded: 'unavailable', reason: 'alternate_screen' }));
    b.Gate.begin(b.ctl, Promise.resolve(null), { holdMs: 99999 });
    await tick(); await tick();
    assert.equal(b.timers.length, 0);
    const sv = b.calls[0].opts.stillValid;
    assert.equal(sv(), true);
    b.ctl._navCurrent = () => false;
    assert.equal(sv(), false);
});
