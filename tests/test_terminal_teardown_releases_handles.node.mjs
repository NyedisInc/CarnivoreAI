import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import { TerminalProvider } from '../web/src/lib/terminal-provider/provider.ts';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal-teardown.js'), 'utf8');

let passes = 0;
let failures = 0;

function test(name, fn) {
    try {
        fn();
        passes += 1;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures += 1;
        console.log(`not ok - ${name}\n  ${err && err.message}`);
    }
}

function loadTeardown() {
    const sandbox = { console: { warn() {}, log() {} } };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.TerminalProvider = TerminalProvider;
    vm.runInContext(SRC, vm.createContext(sandbox), { filename: 'terminal-teardown.js' });
    return sandbox.TerminalTeardown;
}

function fakeClient(extra) {
    const calls = [];
    const ctl = {
        calls,
        queue: [1, 2, 3],
        _queuedBytes: 3,
        flushing: true,
        sessionActive: true,
        _currentSession: { id: 'ses_1' },
        stopReconnecting() { calls.push('stopReconnecting'); },
        pauseForHome() { calls.push('pauseForHome'); },
        _m() { return null; },
        _unsubscribeXtermTheme() { calls.push('themeUnsubscribe'); },
        _xtermOpacity: { apply() {}, dispose() { calls.push('opacityDispose'); } },
        term: { dispose() { calls.push('termDispose'); } },
        fitAddon: {},
    };
    return Object.assign(ctl, extra || {});
}


test('the background-dim observer is disconnected', () => {
    const teardown = loadTeardown();
    const ctl = fakeClient();
    assert.strictEqual(teardown.dispose(ctl), true);
    assert.ok(
        ctl.calls.includes('opacityDispose'),
        'the opacity handle survived the terminal it was watching',
    );
    assert.strictEqual(ctl._xtermOpacity, null, 'the handle must not be reachable after');
});

test('the observer goes BEFORE the emulator it writes into', () => {
    const teardown = loadTeardown();
    const ctl = fakeClient();
    teardown.dispose(ctl);
    assert.ok(
        ctl.calls.indexOf('opacityDispose') < ctl.calls.indexOf('termDispose'),
        `expected the observer released first, got ${ctl.calls.join(' -> ')}`,
    );
});

test('a client that never attached one is not a failure', () => {
    const teardown = loadTeardown();
    const ctl = fakeClient({ _xtermOpacity: undefined });
    assert.strictEqual(teardown.dispose(ctl), true);
    assert.ok(ctl.calls.includes('termDispose'), 'the rest of the teardown still ran');
});

test('a handle whose dispose throws does not strand the emulator', () => {
    const teardown = loadTeardown();
    const ctl = fakeClient({
        _xtermOpacity: { dispose() { throw new Error('observer already gone'); } },
    });
    assert.strictEqual(teardown.dispose(ctl), true);
    assert.ok(ctl.calls.includes('termDispose'), 'xterm was never disposed');
});

test('a second teardown is a no-op', () => {
    const teardown = loadTeardown();
    const ctl = fakeClient();
    teardown.dispose(ctl);
    const after = ctl.calls.length;
    assert.strictEqual(teardown.dispose(ctl), false);
    assert.strictEqual(ctl.calls.length, after, 'the second call did work');
});

test('queued xterm 5.3 viewport callbacks are inert before renderer disposal', () => {
    const teardown = loadTeardown();
    const ctl = fakeClient();
    let renderer = { dimensions: 1 };
    const viewport = {
        syncScrollArea() { return renderer.dimensions; },
        _innerRefresh() { return renderer.dimensions; },
    };
    const constructorTimeout = () => viewport.syncScrollArea();
    const resetFrame = () => viewport._innerRefresh();
    assert.equal(constructorTimeout(), 1);
    ctl.term._core = { viewport };
    ctl.term.dispose = () => {
        renderer = null;
        constructorTimeout();
        resetFrame();
    };
    assert.equal(teardown.dispose(ctl), true);
    assert.doesNotThrow(constructorTimeout);
    assert.doesNotThrow(resetFrame);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
