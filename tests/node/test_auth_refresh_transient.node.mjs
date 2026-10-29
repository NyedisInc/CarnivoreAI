import { strict as assert } from 'node:assert';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const MODULE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js', 'auth.js');

function load(status) {
    const store = new Map([['claude_refresh_token', 'r0']]);
    globalThis.window = globalThis;
    globalThis.localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
    globalThis.API = { baseURL: '' };
    globalThis.fetch = async () => ({ ok: false, status, json: async () => ({}) });
    delete require.cache[require.resolve(MODULE)];
    require(MODULE);
    return globalThis.Auth;
}

for (const [status, want] of [[502, 'network-error'], [503, 'network-error'], [500, 'network-error'], [429, 'network-error'], [408, 'network-error'], [401, false], [403, false], [400, false]]) {
    test(`refresh answering ${status} resolves ${want}`, async () => {
        const auth = load(status);
        assert.equal(await auth._rotate('r0'), want);
    });
}
