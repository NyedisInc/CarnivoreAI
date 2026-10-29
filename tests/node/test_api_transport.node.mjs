
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const API_JS = process.env.API_JS || path.join(ROOT, 'client/js/api.js');

let failures = 0;

async function test(name, fn) {
    try { await fn(); console.log(`ok - ${name}`); } catch (err) {
        failures++; console.error(`NOT OK - ${name}\n${err && err.stack ? err.stack : err}`);
    }
}

function load(answers, refresh = true) {
    const calls = [];
    const state = { refreshes: 0, unauthorized: 0 };
    let token = 'old';
    const store = {};
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, info() {}, error() {} },
        localStorage: {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
            removeItem: (k) => { delete store[k]; },
        },
        async fetch(url, init) {
            calls.push({ url, init });
            const a = answers.shift();
            return { ok: a.status < 300, status: a.status, async json() { return a.body; }, async blob() { return 'blob'; } };
        },
        location: { protocol: 'http:', host: '127.0.0.1:5199' },
        FormData: class { append() {} },
        CustomEvent: class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } },
        dispatchEvent() {},
        Auth: {
            getRefreshToken: () => 'r',
            clearToken() { state.unauthorized++; },
            async refresh() { state.refreshes++; token = 'new'; return refresh; },
        },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(API_JS, 'utf8'), sandbox, { filename: 'api.js' });
    const api = new (sandbox.APIClient || sandbox.API.constructor)();
    api.getToken = () => token;
    return { api, calls, state };
}

await test('call(): a 401 refreshes once and replays with the new token', async () => {
    const { api, calls, state } = load([{ status: 401, body: {} }, { status: 200, body: { ok: 1 } }]);
    assert.deepEqual(await api.call('/x'), { ok: 1 });
    assert.equal(state.refreshes, 1);
    assert.deepEqual(calls.map((c) => c.init.headers.Authorization), ['Bearer old', 'Bearer new']);
});

await test('uploadFile(): the same 401 replay, through the same transport', async () => {
    const { api, calls, state } = load([{ status: 401, body: {} }, { status: 200, body: { path: 'p' } }]);
    assert.deepEqual(await api.uploadFile({ type: 'image/png' }, 'a.png', 's1'), { path: 'p' });
    assert.equal(state.refreshes, 1);
    assert.ok(calls[1].url.endsWith('/sessions/upload-file?session_id=s1'));
    assert.equal(calls[1].init.headers.Authorization, 'Bearer new');
    assert.equal(calls[1].init.headers['Content-Type'], undefined, 'multipart sets its own boundary');
});

await test('a second 401 after the refresh is a hard re-auth, not another refresh', async () => {
    const { api, state } = load([{ status: 401, body: {} }, { status: 401, body: {} }]);
    await assert.rejects(() => api.call('/x'), /Authentication required/);
    assert.equal(state.refreshes, 1);
});

await test('a refresh that hits the network error is a recoverable NetworkUnavailable', async () => {
    const { api } = load([{ status: 401, body: {} }], 'network-error');
    await assert.rejects(() => api.uploadFile({}, 'a'), (e) => e.code === 'NetworkUnavailable' && e.status === 0);
});

await test('a background-image refusal with an object detail never reads [object Object]', async () => {
    const { api } = load([{ status: 413, body: { detail: { code: 'too_big', detail: 'that picture is too big' } } }]);
    await assert.rejects(() => api.uploadSessionBackgroundImage('s', { name: 'a.png' }),
        (e) => e.status === 413 && /too big/.test(e.message) && !/object Object/.test(e.message));
});

await test('call() keeps the whole parsed body on the Error', async () => {
    const { api } = load([{ status: 403, body: { code: 'revoked', detail: 'nope' } }]);
    await assert.rejects(() => api.call('/x'), (e) => e.status === 403 && e.body.code === 'revoked' && e.detail === 'nope');
});

if (failures) process.exit(1);
console.log('ALL PASS');
