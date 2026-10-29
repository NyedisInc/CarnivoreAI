// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;
const queue = [];

/** Queue one named assertion block. Inputs: name, fn. Output: void. */
function test(name, fn) {
    queue.push([name, fn]);
}

/** Run every queued test in order. Inputs: none. Output: Promise<void>. */
async function runQueue() {
    for (const [name, fn] of queue) {
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
}

function clientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

function loadTransport() {
    const sandbox = { console: { log() {} } };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(clientJs('session-transport.js'), sandbox);
    return sandbox.SessionTransport;
}

const T = loadTransport();

test('a fresh module knows nothing about any session', () => {
    assert.equal(T.stateFor('cloude_api'), 'unknown');
    assert.equal(T.stateFor(''), 'unknown');
    assert.equal(T.stateFor(null), 'unknown');
    assert.equal(T.stateFor(undefined), 'unknown');
});

test('marking one session tells you about that session only', () => {
    T.mark('cloude_api', T.DISCONNECTED);
    assert.equal(T.stateFor('cloude_api'), 'disconnected');
    assert.equal(T.stateFor('cloude_other'), 'unknown');
    assert.equal(T.stateFor('CLOUDE_API'), 'unknown', 'names are exact');
});

test('connected is recorded and is not disconnected', () => {
    T.mark('cloude_api', T.CONNECTED);
    assert.equal(T.stateFor('cloude_api'), 'connected');
});

test('an unrecognised state degrades to unknown, never to a red light', () => {
    for (const bogus of ['closing', '', null, undefined, 0, {}]) {
        T.mark('cloude_api', bogus);
        assert.equal(T.stateFor('cloude_api'), 'unknown', `bogus: ${bogus}`);
    }
});

test('clear forgets everything - a detach is not a disconnection', () => {
    T.mark('cloude_api', T.DISCONNECTED);
    T.clear();
    assert.equal(T.stateFor('cloude_api'), 'unknown');
    T.mark(null, T.DISCONNECTED);
    assert.equal(T.stateFor('cloude_api'), 'unknown', 'a falsy name clears too');
});

test('only ONE session is held at a time, because only one socket exists', () => {
    T.mark('cloude_a', T.DISCONNECTED);
    T.mark('cloude_b', T.CONNECTED);
    assert.equal(T.stateFor('cloude_b'), 'connected');
    assert.equal(T.stateFor('cloude_a'), 'unknown');
});

test('the module needs no window and no DOM', () => {
    const src = clientJs('session-transport.js');
    assert.ok(!/\bdocument\./.test(src), 'no DOM access');
    assert.ok(!/\bwindow\./.test(src), 'no window access');
    assert.ok(!/\bfetch\(/.test(src), 'no network access');
});

test('TERMINAL.JS ACTUALLY WRITES IT - all three transitions', () => {
    const src = clientJs('terminal.js');
    assert.ok(src.includes('SessionTransport.CONNECTED'),
        'ws.onopen must record the socket coming up');
    assert.ok(src.includes('SessionTransport.DISCONNECTED'),
        'ws.onclose must record the socket dropping');
    assert.ok(src.includes('SessionTransport.clear()'),
        'a deliberate close must clear rather than mark disconnected');
    const start = src.indexOf('if (this._intentionalClose) {');
    const branch = src.slice(start, src.indexOf('\n            }', start));
    assert.ok(branch.includes('SessionTransport.clear()'));
    assert.ok(!branch.includes('SessionTransport.DISCONNECTED'));
});

test('THE READERS ACTUALLY READ IT - both session surfaces', () => {
    // the legacy twin
    const shell = (f) => fs.readFileSync(
        path.join(__dirname, '..', 'web', 'src', 'lib', 'sidebar-shell', f), 'utf8');
    assert.ok(shell('row-host.ts').includes('SessionTransport'),
        'the sidebar row host must read the transport state');
    assert.ok(/transport: host\.transport/.test(shell('row-plan.ts'))
        && /<SessionFace[^>]*facts=\{\{[^}]*\.\.\.p\.led/.test(shell('SessionRow.svelte')),
        'the sidebar row must pass the transport state into the LED');
    const host = fs.readFileSync(
        path.join(__dirname, '..', 'web', 'src', 'lib', 'launchpad',
            'running-host.ts'), 'utf8');
    assert.ok(host.includes('SessionTransport'),
        'the running-sessions host must read the transport state');
});

test('the module is SERVED - a file nobody loads is dead code', () => {
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    assert.ok(html.includes('/static/js/session-transport.js'));
    const me = html.indexOf('<script src="/static/js/session-transport.js"></script>');
    assert.ok(me > -1, 'the script tag itself is present');
    // the home screen
    for (const after of ['<script src="/static/js/terminal.js"></script>',
        '<script type="module" src="/static/dist/app.js"></script>']) {
        const at = html.indexOf(after);
        assert.ok(at > me, `must load before ${after}`);
    }
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
