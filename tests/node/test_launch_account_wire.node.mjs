
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

function loadApi() {
    const calls = [];
    const context = {
        window: { location: { protocol: 'http:', host: 'example.test:5055' } },
        localStorage: { getItem: (k) => (k === 'claude_tunnel_token' ? 'test-jwt' : null), setItem() {}, removeItem() {} },
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout, clearTimeout, AbortController,
        async fetch(url, options) {
            calls.push({ url, options });
            return { status: 200, ok: true, headers: { get() { return null; } }, async json() { return { status: 'started' }; } };
        },
    };
    context.globalThis = context;
    vm.createContext(context);
    for (const f of ['api.js', 'api-session-lifecycle.js']) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, 'client', 'js', f), 'utf8'), context, { filename: f });
    }
    return { api: context.window.API, calls };
}

function bodyOf(calls) {
    assert.equal(calls.length, 1);
    const b = calls[0].options.body;
    return b === undefined ? null : typeof b === 'string' ? JSON.parse(b) : b;
}

const CHOICE = { accountId: 'play', pinned: true };
const cases = [
    ['wake', (a, acct) => a.wakeSession('u1', 'cld', acct)],
    ['recreate', (a, acct) => a.recreateSession('u1', 'cld', acct)],
    ['respawn', (a, acct) => a.respawnSession('carnivore_x', 'cld', false, acct)],
];
for (const [name, call] of cases) {
    let { api, calls } = loadApi();
    await call(api, CHOICE);
    let body = bodyOf(calls);
    assert.equal(body.account_id, 'play', `${name} sends account_id`);
    assert.equal(body.account_pinned, true, `${name} sends account_pinned`);
    ({ api, calls } = loadApi());
    await call(api, { accountId: 'work', pinned: false });
    body = bodyOf(calls);
    assert.deepEqual([body.account_id, body.account_pinned], ['work', false], `${name} unticked sends false`);
    ({ api, calls } = loadApi());
    await call(api, null);
    body = bodyOf(calls);
    assert.ok(!body || (!('account_id' in body) && !('account_pinned' in body)), `${name} collapsed sends no account`);
    console.log(`ok - ${name} body`);
}
