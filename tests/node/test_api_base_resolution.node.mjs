
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = process.argv[2] || path.join(__dirname, '..', '..', 'client/js/api.js');

let failures = 0;

function build(location, baseURI) {
    const store = {};
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, info() {}, error() {} },
        localStorage: {
            getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
            setItem(k, v) { store[k] = String(v); },
            removeItem(k) { delete store[k]; },
        },
        async fetch() { throw new Error('no network in this test'); },
        URL,
        location,
        document: { baseURI },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(SOURCE, 'utf8'), sandbox, { filename: 'api.js' });
    const Ctor = sandbox.APIClient || (sandbox.API && sandbox.API.constructor);
    assert.ok(Ctor, 'api.js did not expose an APIClient constructor into the sandbox');
    const api = new Ctor();
    return { baseURL: api.baseURL, wsBaseURL: api.wsBaseURL };
}

function test(name, fn) {
    try {
        fn();
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.message ? err.message : err);
    }
}

test('a normal page resolves the base from its own location', () => {
    const got = build({ protocol: 'http:', host: '127.0.0.1:5199' }, 'http://127.0.0.1:5199/');
    assert.equal(got.baseURL, 'http://127.0.0.1:5199/api/v1');
    assert.equal(got.wsBaseURL, 'ws://127.0.0.1:5199');
});

test('a normal https page keeps https and wss', () => {
    const got = build({ protocol: 'https:', host: 'carnivore.example:8443' }, 'https://carnivore.example:8443/');
    assert.equal(got.baseURL, 'https://carnivore.example:8443/api/v1');
    assert.equal(got.wsBaseURL, 'wss://carnivore.example:8443');
});

test('an about:srcdoc frame resolves the base from its embedding page (document.baseURI), not an empty host', () => {
    const got = build({ protocol: 'about:', host: '' }, 'http://127.0.0.1:5199/static/index.html');
    assert.equal(got.baseURL, 'http://127.0.0.1:5199/api/v1');
    assert.equal(got.wsBaseURL, 'ws://127.0.0.1:5199');
});

if (failures) {
    console.error(`${failures} failed`);
    process.exit(1);
}
