import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
let failures = 0;

async function test(name, fn) {
    try { await fn(); console.log(`ok - ${name}`); } catch (err) { failures++; console.error(`NOT OK - ${name}\n${err.stack || err}`); }
}

function loadApi({ status, body }) {
    const events = [];
    const store = {};
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, info() {}, error() {} },
        localStorage: {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
            removeItem: (k) => { delete store[k]; },
        },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
        dispatchEvent(event) { events.push(event); return true; },
        async fetch() { return { ok: status >= 200 && status < 300, status, async json() { return body; } }; },
        location: { protocol: 'http:', host: '127.0.0.1:5199' },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js/api.js'), 'utf8'), sandbox, { filename: 'api.js' });
    const Ctor = sandbox.APIClient || (sandbox.API && sandbox.API.constructor);
    assert.ok(Ctor, 'api.js did not expose an APIClient constructor');
    const api = new Ctor();
    api.handleUnauthorized = () => {};
    return { api, events };
}

await test('an account_required 403 dispatches cloude:api-refusal with status and body', async () => {
    const body = { code: 'account_required', feature: 'share_link', detail: 'sign in' };
    const { api, events } = loadApi({ status: 403, body });
    await assert.rejects(() => api.call('/sessions/s1/share'));
    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'cloude:api-refusal');
    assert.equal(events[0].detail.status, 403);
    assert.deepEqual(events[0].detail.body, body);
});

await test('an app-login 401 dispatches no refusal event', async () => {
    const { api, events } = loadApi({ status: 401, body: { detail: 'Not authenticated' } });
    await assert.rejects(() => api.call('/sessions/list'));
    assert.deepEqual(events, []);
});

await test('a success dispatches nothing', async () => {
    const { api, events } = loadApi({ status: 200, body: { ok: true } });
    await api.call('/anything');
    assert.deepEqual(events, []);
});

process.exit(failures === 0 ? 0 : 1);
