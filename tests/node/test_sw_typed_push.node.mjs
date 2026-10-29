
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client', 'sw.js'), 'utf8');

function load(windows = []) {
    const listeners = {};
    const shown = [];
    const calls = [];
    const self = {
        location: { origin: 'https://app.example' },
        addEventListener: (type, fn) => { listeners[type] = fn; },
        skipWaiting() {}, registration: { showNotification: (t, o) => { shown.push({ title: t, options: o }); return Promise.resolve(); } },
        clients: {
            claim() {},
            matchAll: () => Promise.resolve(windows),
            openWindow: (u) => { calls.push(['open', u]); return Promise.resolve(); },
        },
    };
    vm.runInNewContext(SRC, { self, URL, console });
    return { listeners, shown, calls };
}

async function push(env, value) {
    let waited;
    const data = value === undefined ? null : { json: () => { if (value === 'throw') throw new SyntaxError('x'); return value; } };
    env.listeners.push({ data, waitUntil: (p) => { waited = p; } });
    await waited;
    return env.shown.at(-1);
}

async function click(windows, data) {
    const env = load(windows);
    let waited;
    env.listeners.notificationclick({ notification: { close() {}, data }, waitUntil: (p) => { waited = p; } });
    await waited;
    return env.calls;
}

function win(calls) {
    const w = { focus: () => { calls.push(['focus']); return Promise.resolve(w); }, navigate: (u) => { calls.push(['navigate', u]); return Promise.resolve(w); } };
    return w;
}

let n = await push(load(), { title: 'Q needs you', body: 'session foo', path: '/s/foo' });
assert.equal(n.title, 'Q needs you');
assert.equal(n.options.body, 'session foo');
assert.equal(n.options.data.path, '/s/foo');
assert.equal(n.options.tag, undefined);

for (const v of ['throw', undefined, {}, { title: 5, body: null }]) {
    n = await push(load(), v);
    assert.equal(n.title, 'carnivore');
    assert.equal(n.options.body, 'approval needed');
    assert.equal(n.options.tag, 'approval');
    assert.equal(n.options.data.path, null);
}

n = await push(load(), { body: 'only body' });
assert.equal(n.title, 'carnivore');
assert.equal(n.options.body, 'only body');

for (const bad of ['//example.net', '/\\example.net', 'https://example.net', 'evil', '', '/a\nb', '/\t/example.net', '/a\\b', 7, null]) {
    n = await push(load(), { title: 't', body: 'b', path: bad });
    assert.equal(n.options.data.path, null, `push path ${JSON.stringify(bad)}`);
    let calls = await click([], { path: bad });
    assert.deepEqual(calls, [['open', '/']], `click path ${JSON.stringify(bad)}`);
}

assert.deepEqual(await click([], { path: '/s/foo?x=1#h' }), [['open', '/s/foo?x=1#h']]);
assert.deepEqual(await click([], undefined), [['open', '/']]);
const calls = [];
await (async () => {
    const env = load([win(calls)]);
    let waited;
    env.listeners.notificationclick({ notification: { close() {}, data: { path: '/s/foo' } }, waitUntil: (p) => { waited = p; } });
    await waited;
})();
assert.deepEqual(calls, [['focus'], ['navigate', '/s/foo']]);
const calls2 = [];
await (async () => {
    const env = load([win(calls2)]);
    let waited;
    env.listeners.notificationclick({ notification: { close() {}, data: { path: '//example.net' } }, waitUntil: (p) => { waited = p; } });
    await waited;
})();
assert.deepEqual(calls2, [['focus'], ['navigate', '/']]);

const askPath = '/?approvals=ses_1';
const askCalls = [];
await (async () => {
    const w = win(askCalls);
    w.postMessage = (m) => askCalls.push(['message', m]);
    const env = load([w]);
    let waited;
    env.listeners.notificationclick({ notification: { close() {}, data: { path: askPath } }, waitUntil: (p) => { waited = p; } });
    await waited;
})();
assert.equal(JSON.stringify(askCalls), JSON.stringify([['focus'], ['message', { type: 'carnivore.open-approval', session_id: 'ses_1' }]]));
assert.deepEqual(await click([], { path: askPath }), [['open', askPath]]);

console.log('ok test_sw_typed_push');
