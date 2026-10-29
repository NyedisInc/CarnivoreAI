
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const WITH_PRIMITIVE = !process.argv.includes('--no-primitive');
let failures = 0;

/** Run one named block, recording failure instead of throwing. */
async function test(name, fn) {
    try { await fn(); console.log(`ok - ${name}`); } catch (err) { failures++; console.error(`not ok - ${name}\n${err.stack || err}`); }
}

function load(answer, opts = {}) {
    const requests = [];
    const store = { claude_tunnel_token: 'tok' };
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, info() {}, error() {} },
        localStorage: {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
            removeItem: (k) => { delete store[k]; },
        },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
        dispatchEvent() { return true; },
        location: { protocol: 'http:', host: '127.0.0.1:5199' },
        setTimeout,
        JSON,
        Date,
    };
    sandbox.fetch = async (url, init = {}) => {
        requests.push({ url, init });
        const n = requests.length;
        await new Promise((resolve) => setTimeout(resolve, 5));
        const { status, body } = answer(url, init, n);
        return { ok: status >= 200 && status < 300, status, async json() { return JSON.parse(JSON.stringify(body)); } };
    };
    if (opts.auth) sandbox.Auth = opts.auth;
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    if ((opts.primitive ?? WITH_PRIMITIVE)) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js/boot-fetch-dedupe.js'), 'utf8'), sandbox, { filename: 'boot-fetch-dedupe.js' });
    }
    vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js/api.js'), 'utf8'), sandbox, { filename: 'api.js' });
    const Ctor = sandbox.APIClient || (sandbox.API && sandbox.API.constructor);
    assert.ok(Ctor, 'api.js did not expose an APIClient constructor');
    const api = new Ctor();
    api.handleUnauthorized = () => {};
    return { api, sandbox, requests };
}

const ok = (body) => () => ({ status: 200, body });

await test('1. ten concurrent GETs of one path send one request; each waiter gets its own copy', async () => {
    const { api, requests } = load(ok({ rows: [{ id: 1 }] }));
    const answers = await Promise.all(Array.from({ length: 10 }, () => api.call('/projects')));
    assert.equal(requests.length, 1, `expected 1 request, saw ${requests.length}`);
    assert.deepEqual(answers[0], { rows: [{ id: 1 }] });
    answers[0].rows[0].id = 99;
    assert.equal(answers[1].rows[0].id, 1, 'a waiter mutated another waiter\'s answer');
    assert.notEqual(answers[1], answers[2]);
});

await test('2. a settled OK answer is reused only for the reuse span, then a GET fetches again; a write clears it; a failure is never kept', async () => {
    const { api, sandbox, requests } = load(ok([]));
    let t = 1000;
    sandbox.BootFetchDedupe.configure({ now: () => t, windowMs: 8000, reuseMs: 1500 });
    await api.call('/projects');
    t += 100;
    await api.call('/projects');
    assert.equal(requests.length, 1, 'a second wave 100 ms later must reuse the settled answer');
    t += 2000;
    await api.call('/projects');
    assert.equal(requests.length, 2, 'past the reuse span the GET fetches again');
    await api.call('/projects', { method: 'POST', body: { a: 1 } });
    await api.call('/projects');
    assert.equal(requests.length, 4, 'a write clears the settled answer (the POST, then a fresh GET)');
    const failing = load((url, init, n) => (n === 1 ? { status: 500, body: { detail: 'x' } } : { status: 200, body: [1] }));
    await assert.rejects(() => failing.api.call('/themes'));
    assert.deepEqual(await failing.api.call('/themes'), [1]);
    assert.equal(failing.requests.length, 2, 'a failed answer must not be reused');
});

await test('3. the query is part of the key; a POST is never shared and forgets its family', async () => {
    const { api, requests } = load(ok({ ok: true }));
    await Promise.all([api.call('/sessions?session_id=a'), api.call('/sessions?session_id=a&include_scrollback=1'), api.call('/sessions?session_id=a')]);
    assert.equal(requests.length, 2, 'the plain and the scrollback read must stay two requests');
    requests.length = 0;
    const first = api.call('/projects');
    const write1 = api.call('/projects', { method: 'POST', body: { a: 1 } });
    const write2 = api.call('/projects', { method: 'POST', body: { a: 1 } });
    const second = api.call('/projects');
    await Promise.all([first, write1, write2, second]);
    const gets = requests.filter((r) => !r.init.method || r.init.method === 'GET').length;
    const posts = requests.filter((r) => r.init.method === 'POST').length;
    assert.equal(posts, 2, 'a POST was shared');
    assert.equal(gets, 2, 'a GET issued after a write joined a read that started before it');
});

await test('4. a rejection reaches every waiter once and clears the slot; a 401 refreshes once for all waiters', async () => {
    const { api, requests } = load((url, init, n) => (n === 1 ? { status: 500, body: { detail: 'boom' } } : { status: 200, body: { fine: true } }));
    const settled = await Promise.allSettled(Array.from({ length: 5 }, () => api.call('/themes')));
    assert.equal(requests.length, 1);
    assert.ok(settled.every((s) => s.status === 'rejected' && s.reason.message === 'boom'), 'every waiter must see the shared error');
    assert.deepEqual(await api.call('/themes'), { fine: true });
    assert.equal(requests.length, 2, 'the failed slot must be gone');

    let refreshes = 0;
    let refreshed = false;
    const auth = { getRefreshToken: () => 'r', async refresh() { refreshes++; refreshed = true; return true; } };
    const two = load(() => (refreshed ? { status: 200, body: { v: 1 } } : { status: 401, body: {} }), { auth });
    const got = await Promise.all(Array.from({ length: 6 }, () => two.api.call('/layouts')));
    assert.ok(got.every((g) => g.v === 1));
    assert.equal(refreshes, 1, `expected one refresh, saw ${refreshes}`);
    assert.equal(two.requests.length, 2, 'one 401 and one replay for all six waiters');
});

await test('5. after the boot window calls are not shared; with the primitive absent API.call is unchanged', async () => {
    const { api, sandbox, requests } = load(ok([]));
    let t = 1000;
    sandbox.BootFetchDedupe.configure({ now: () => t, windowMs: 8000, reuseMs: 1500 });
    await Promise.all([api.call('/companies'), api.call('/companies')]);
    assert.equal(requests.length, 1, 'inside the window the pair shares');
    t += 8001;
    requests.length = 0;
    await Promise.all([api.call('/companies'), api.call('/companies')]);
    assert.equal(requests.length, 2, 'after the window the pair does not share');
    const bare = load(ok([1]), { primitive: false });
    const out = await Promise.all([bare.api.call('/x'), bare.api.call('/x')]);
    assert.equal(bare.requests.length, 2);
    assert.deepEqual(out, [[1], [1]]);
});

await test('6. the G2 duplicate list sends one request per path', async () => {
    const dups = { '/sessions/recent': 4, '/projects': 4, '/layouts': 4, '/themes': 5, '/companies': 4, '/sessions/asleep': 3, '/catalog/items': 4, '/provider-ledger': 4, '/item-settings': 4, '/browsers': 4, '/browsers/pages': 4, '/files/open': 4 };
    const { api, requests } = load(ok({ x: 1 }));
    const calls = [];
    for (const [p, n] of Object.entries(dups)) for (let i = 0; i < n; i++) calls.push(api.call(p));
    await Promise.all(calls);
    assert.equal(requests.length, Object.keys(dups).length, `${calls.length} calls sent ${requests.length} requests`);
});

await test('7. calls that carry headers, a body or a signal are never shared', async () => {
    const { api, requests } = load(ok({}));
    await Promise.all([api.call('/x', { headers: { Accept: 'a' } }), api.call('/x', { headers: { Accept: 'a' } })]);
    assert.equal(requests.length, 2);
});

await test('9. a write forgets only its own resource family; a write to the same family forgets the settled answer', async () => {
    const { api, requests } = load(ok({ v: 1 }));
    await api.call('/projects');
    await api.call('/catalog/refresh', { method: 'POST', body: {} });
    await api.call('/projects');
    assert.equal(requests.filter((r) => r.url.endsWith('/projects')).length, 1, 'a catalog write must not throw away the settled /projects answer');
    await api.call('/projects/x/move', { method: 'POST', body: {} });
    await api.call('/projects');
    assert.equal(requests.filter((r) => r.url.endsWith('/projects')).length, 2, 'a projects write must forget the settled /projects answer');
});

function bodyOf(src, signature) {
    const m = signature.exec(src);
    if (!m) return null;
    const rest = src.slice(m.index);
    const end = rest.indexOf('\n}\n');
    return end === -1 ? rest : rest.slice(0, end);
}

function wiredOnlyInAuthFetch(src) {
    const a = bodyOf(src, /export function authFetch</);
    const b = bodyOf(src, /export function authFetchBlob\(/);
    const r = bodyOf(src, /async function request[<(]/) ?? bodyOf(src, /function request[<(]/);
    return Boolean(a && a.includes('BootFetchDedupe') && b && !b.includes('BootFetchDedupe') && r && !r.includes('BootFetchDedupe'));
}

await test('8. web side: authFetch shares, authFetchBlob and request do not (with a control)', async () => {
    const real = fs.readFileSync(path.join(ROOT, 'web/src/opscenter/api/auth.svelte.ts'), 'utf8');
    assert.ok(wiredOnlyInAuthFetch(real), 'auth.svelte.ts must call BootFetchDedupe from authFetch only');
    const neither = 'export function authFetch<T>() {\n  return 1;\n}\nexport function authFetchBlob(p) {\n  return 2;\n}\nasync function request<T>() {\n  return 3;\n}\n';
    assert.equal(wiredOnlyInAuthFetch(neither), false, 'the scan must fail on a file that wires nothing');
    const registry = fs.readFileSync(path.join(ROOT, 'client/js/themes/registry.js'), 'utf8');
    assert.ok(bodyOf(registry, /async function fetchManifests\(/)?.includes('BootFetchDedupe'), 'fetchManifests must go through the sharer');
});

process.exit(failures === 0 ? 0 : 1);
