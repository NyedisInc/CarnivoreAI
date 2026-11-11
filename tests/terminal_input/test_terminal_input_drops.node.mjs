import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal-input-drops.js'), 'utf8');

function make() {
    const calls = [];
    const sandbox = {
        console, Date, Math, JSON, Promise,
        performance: { now: () => 4321 },
        document: { visibilityState: 'visible', activeElement: null },
        TerminalInputFocus: { current: () => 'terminal:row:32' },
        API: { rawCall: (route, init) => { calls.push({ route, init }); return Promise.resolve({}); } },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(SRC, sandbox);
    return { D: sandbox.TerminalInputDrops, calls };
}

test('a refused write reports once per slot and reason, with the documented fields and no key content', () => {
    const { D, calls } = make();
    const term = { _inputOwner: '@primary', ws: { readyState: 1 } };
    D.record('owner_refused', term, { phase: 'ready' });
    D.record('owner_refused', term, { phase: 'ready' });
    assert.equal(calls.length, 1, 'second report inside 10 s is suppressed');
    assert.equal(D.ring().length, 2, 'the ring keeps both');
    const body = JSON.parse(calls[0].init.body);
    assert.deepEqual(Object.keys(body).sort(), [
        'active_slot', 'buffer_phase', 'hidden', 'owner', 'page_ms', 'reason', 'slot', 'ws_state']);
    assert.equal(body.slot, '@primary');
    assert.equal(body.owner, 'terminal:row:32');
    assert.equal(body.ws_state, 1);
    assert.equal(body.page_ms, 4321);
    assert.equal(calls[0].route, '/terminal/input-drops');
    D.record('no_socket', term);
    assert.equal(calls.length, 2, 'a different reason reports');
});

test('the ring keeps the last 50 and a missing API never throws', () => {
    const { D } = make();
    for (let i = 0; i < 60; i++) D.record('no_socket', { _inputOwner: 's' + i });
    assert.equal(D.ring().length, 50);
});

test('buffer-side verdicts report held_pre_ready, buffer_overflow, buffer_poisoned and stale_generation', () => {
    const buf = path.join(ROOT, 'client/js/terminal-input-buffer.js');
    const { D, calls } = make();
    const reasons = [];
    D.record = (reason) => reasons.push(reason);
    let now = 1000;
    const sb = {
        console, Date: { now: () => now }, Math, JSON, Uint8Array, setTimeout, clearTimeout,
        TerminalInputDrops: D,
    };
    sb.window = sb; sb.global = sb; sb.globalThis = sb;
    vm.createContext(sb);
    vm.runInContext(fs.readFileSync(buf, 'utf8'), sb);
    assert.ok(sb.TerminalInputBuffer, 'buffer module loaded');
    const B = sb.TerminalInputBuffer;
    const ctl = { ws: { readyState: 0, send() {} } };
    B.arm('t');
    ctl._connGen = B.arm('t2');
    B.send(ctl, new Uint8Array([97]));
    assert.deepEqual(reasons, [], 'a fresh hold is not reported');
    now += 2500;
    B.send(ctl, new Uint8Array([97]));
    assert.deepEqual(reasons, ['held_pre_ready']);
    B.send(ctl, new Uint8Array(70 * 1024));
    assert.ok(reasons.includes('buffer_overflow'));
    B.send(ctl, new Uint8Array([97]));
    assert.ok(reasons.includes('buffer_poisoned'));
    B.arm('t3');
    B.send(ctl, new Uint8Array([97]));
    assert.ok(reasons.includes('stale_generation'));
    assert.equal(calls.length, 0);
});
