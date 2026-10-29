
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

let failures = 0;
let passes = 0;

async function test(name, fn) {
    try {
        await fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function loadApi({ status, body }) {
    const errors = [];
    const quiet = [];
    const store = {};
    const sandbox = {
        console: {
            log() {},
            warn() {},
            debug(...a) { quiet.push(String(a[0])); },
            info(...a) { quiet.push(String(a[0])); },
            error(...a) { errors.push(String(a[0])); },
        },
        localStorage: {
            getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
            setItem(k, v) { store[k] = String(v); },
            removeItem(k) { delete store[k]; },
        },
        async fetch() {
            return {
                ok: status >= 200 && status < 300,
                status,
                async json() { return body; },
            };
        },
        location: { protocol: 'http:', host: '127.0.0.1:5199' },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    const src = fs.readFileSync(path.join(ROOT, 'client/js/api.js'), 'utf8');
    vm.runInContext(src, sandbox, { filename: 'api.js' });
    const Ctor = sandbox.APIClient || (sandbox.API && sandbox.API.constructor);
    assert.ok(Ctor, 'api.js did not expose an APIClient constructor into the sandbox');
    return { api: new Ctor(), errors, quiet };
}

await test('an expected 404 from GET /sessions is NOT logged as console.error', async () => {
    const { api, errors } = loadApi({ status: 404, body: { detail: 'No active session' } });
    const result = await api.getCurrentSession();
    assert.equal(result, null, 'getCurrentSession must still resolve to null on 404');
    const sessionErrors = errors.filter(line => line.includes('/sessions'));
    assert.deepEqual(
        sessionErrors, [],
        `expected no console.error for the documented 404, got: ${JSON.stringify(sessionErrors)}`
    );
});

await test('POSITIVE CONTROL: an UNEXPECTED status on the same call site still logs', async () => {
    const { api, errors } = loadApi({ status: 500, body: { detail: 'boom' } });
    await assert.rejects(
        () => api.getCurrentSession(),
        /boom/,
        'a 500 must still propagate to the caller'
    );
    const sessionErrors = errors.filter(line => line.includes('/sessions'));
    assert.ok(
        sessionErrors.length >= 1,
        'a 500 must still reach console.error - silencing every status would be worse '
        + 'than the bug being fixed'
    );
});

await test('an unrelated endpoint 404 is still logged as an error', async () => {
    const { api, errors } = loadApi({ status: 404, body: { detail: 'Not Found' } });
    await assert.rejects(() => api.call('/definitely-not-a-route'));
    assert.ok(
        errors.some(line => line.includes('definitely-not-a-route')),
        'only the call sites that DECLARE a status expected may go quiet'
    );
});

await test('a 400 validation refusal from the ledger write is NOT logged as an error', async () => {
    const { api, errors } = loadApi({
        status: 400,
        body: { detail: [{ loc: ['body', 'name'], msg: 'name must not be empty', type: 'value_error' }] },
    });
    await assert.rejects(() => api.saveProviderAccount('max-main', { name: '' }));
    const ledgerErrors = errors.filter(line => line.includes('provider-ledger'));
    assert.deepEqual(
        ledgerErrors, [],
        `a declared 400 must not reach console.error, got: ${JSON.stringify(ledgerErrors)}`
    );
});

await test('POSITIVE CONTROL: a 500 from the same ledger write still logs', async () => {
    const { api, errors } = loadApi({ status: 500, body: { detail: 'boom' } });
    await assert.rejects(() => api.saveProviderAccount('max-main', { name: 'Max main' }));
    assert.ok(
        errors.some(line => line.includes('provider-ledger')),
        'declaring 400 expected must not silence every other status'
    );
});

await test('the refusal detail still reaches the caller for the form to render', async () => {
    const detail = [{ loc: ['body', 'name'], msg: 'name must not be empty', type: 'value_error' }];
    const { api } = loadApi({ status: 400, body: { detail } });
    await api.saveProviderAccount('max-main', { name: '' }).then(
        () => assert.fail('a refusal must still throw'),
        (err) => {
            assert.equal(err.status, 400);
            assert.deepEqual(err.detail, detail, 'the editor reads the entries off err.detail');
        }
    );
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
