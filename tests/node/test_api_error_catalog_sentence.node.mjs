import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
let failures = 0;

/** Run one named block, recording failure instead of throwing. */
async function test(name, fn) {
    try { await fn(); console.log(`ok - ${name}`); } catch (err) { failures++; console.error(`NOT OK - ${name}\n${err.stack || err}`); }
}

function catalogSentences() {
    const text = fs.readFileSync(path.join(ROOT, 'client/js/i18n/catalog.en.js'), 'utf8');
    const out = {};
    for (const m of text.matchAll(/^\s*'(api\.error\.[a-z0-9_]+)':\s*'((?:[^'\\]|\\.)*)',\s*$/gm)) out[m[1]] = m[2];
    return out;
}

function loadApi(status, body) {
    const sentences = catalogSentences();
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, info() {}, error() {} },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
        dispatchEvent() { return true; },
        CloudeI18n: { t: (key) => sentences[key] || key },
        async fetch() { return { ok: false, status, async json() { return body; } }; },
        location: { protocol: 'http:', host: '127.0.0.1:5199' },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js/api.js'), 'utf8'), sandbox, { filename: 'api.js' });
    const api = new (sandbox.APIClient || sandbox.API.constructor)();
    api.handleUnauthorized = () => {};
    return api;
}

await test('a known code shows the catalog sentence and keeps the code on err.detail', async () => {
    const api = loadApi(500, { detail: { code: 'session_create_failed', detail: 'raw /Users/x/secret' } });
    const err = await api.call('/sessions').catch((e) => e);
    assert.equal(err.message, catalogSentences()['api.error.session_create_failed']);
    assert.equal(err.detail.code, 'session_create_failed');
    assert.ok(!err.message.includes('/Users'));
});

await test('an unknown code keeps the server sentence', async () => {
    const err = await loadApi(409, { detail: { code: 'not_in_catalog', detail: 'the server sentence' } }).call('/x').catch((e) => e);
    assert.equal(err.message, 'the server sentence');
});

await test('a plain string detail with no code is unchanged', async () => {
    const err = await loadApi(404, { detail: 'No active session' }).call('/x').catch((e) => e);
    assert.equal(err.message, 'No active session');
});

process.exit(failures === 0 ? 0 : 1);
