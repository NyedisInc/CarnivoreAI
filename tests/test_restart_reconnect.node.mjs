// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');
const watchSrc = fs.readFileSync(path.join(CLIENT_JS, 'server-restart-watch.js'), 'utf8');
const policySrc = fs.readFileSync(
    path.join(CLIENT_JS, 'terminal-reconnect-policy.js'), 'utf8');
const pageOwnerSrc = fs.readFileSync(
    path.join(CLIENT_JS, 'terminal-page-owner.js'), 'utf8');
const terminalSrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal.js'), 'utf8');

const FAST_WATCH_OPTIONS = Object.freeze({
    origin: 'http://test.invalid',
    firstDelayMs: 1,
    maxDelayMs: 2,
    backoffFactor: 1,
    ceilingMs: 500,
    probeTimeoutMs: 50,
    offlineRecheckMs: 1,
});

const TMUX_NAME = 'cloude_my-project';

let failures = 0;
let passes = 0;

function test(name, fn) {
    return (async () => {
        try {
            await fn();
            passes++;
            console.log(`ok - ${name}`);
        } catch (err) {
            failures++;
            console.error(`NOT OK - ${name}`);
            console.error(err && err.stack ? err.stack : err);
        }
    })();
}

async function waitFor(predicate, timeoutMs = 2000) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
        if (predicate()) return;
        if (Date.now() > deadline) throw new Error('waitFor timed out');
        await new Promise((r) => setTimeout(r, 2));
    }
}

function makeHealthFetch({ failCount = 0, onCall = null } = {}) {
    const calls = [];
    const fetchImpl = async (url) => {
        calls.push(url);
        const index = calls.length;
        if (typeof onCall === 'function') onCall(index);
        if (index <= failCount) {
            const err = new TypeError('fetch failed');
            throw err;
        }
        return { ok: true, status: 200 };
    };
    return { fetchImpl, calls };
}

function makeSandbox({
    failCount = 0, onCall = null, attachable = null, live = [],
    online = null, lazyWatch = false, pageOwner = true,
} = {}) {
    const calls = [];
    const statuses = [];
    const lines = [];

    const fakeDocument = {
        getElementById() { return null; },
        querySelectorAll() { return []; },
        createElement() {
            return { addEventListener() {}, classList: { add() {}, remove() {} }, style: {}, dataset: {} };
        },
    };

    const fakeWindow = {
        location: { origin: FAST_WATCH_OPTIONS.origin, protocol: 'http:', host: 'test.invalid' },
        API: {
            async listAttachableSessions() {
                calls.push(['listAttachableSessions']);
                return fakeWindow.__attachable;
            },
            async listSessions() {
                calls.push(['listSessions']);
                return fakeWindow.__live;
            },
            async adoptSession(name, withScrollback) {
                calls.push(['adoptSession', name, withScrollback]);
                return {
                    session: { id: 'sid-new', tmux_session: name, working_dir: '/tmp/proj' },
                    initial_scrollback_b64: '',
                };
            },
            async createSession(payload) {
                calls.push(['createSession', payload]);
                throw new Error('TEST HARNESS: createSession must never be called from restart recovery');
            },
        },
        dispatchEvent(evt) { calls.push(['dispatchEvent', evt && evt.type]); },
        CustomEvent: function CustomEvent(type, opts) { this.type = type; this.detail = opts && opts.detail; },
        addEventListener() {},
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
    };
    fakeWindow.window = fakeWindow;
    fakeWindow.__attachable = (attachable === null)
        ? [{ name: TMUX_NAME, created_by_cloude: true }]
        : attachable;
    fakeWindow.__live = live;

    const context = {
        window: fakeWindow,
        document: fakeDocument,
        console,
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
        AbortController,
        CustomEvent: fakeWindow.CustomEvent,
        WebSocket: { OPEN: 1, CLOSED: 3 },
    };
    vm.createContext(context);
    vm.runInContext(watchSrc, context, { filename: 'server-restart-watch.js' });
    vm.runInContext(policySrc, context, { filename: 'terminal-reconnect-policy.js' });
    // terminal.js's boot line is one call into the terminal client
    // factory, so the factory has to be in this sandbox first, exactly
    // as index.html loads it first.
    vm.runInContext(fs.readFileSync(
        path.join(CLIENT_JS, 'terminal-client-factory.js'), 'utf8'),
        context, { filename: 'terminal-client-factory.js' });
    vm.runInContext(pageOwnerSrc, context, { filename: 'terminal-page-owner.js' });
    vm.runInContext(terminalSrc, context, { filename: 'terminal.js' });
    if (!context.window.TerminalReconnectPolicy) {
        throw new Error(
            'terminal-reconnect-policy.js did not export itself into the '
            + 'sandbox, so every close would take the plain retry and this '
            + 'suite would be measuring a harness bug');
    }

    const terminal = pageOwner
        ? context.window.TerminalController
        : context.window.CloudeTerminal.createTerminalClient(
            null, { chrome: {}, role: { primary: true } });
    terminal.sessionActive = true;
    terminal._currentSession = { id: 'sid-old', tmux_session: TMUX_NAME };
    terminal.term = { writeln(text) { lines.push(text); } };
    terminal.statusEl = {
        setAttribute(key, value) { if (key === 'data-status') statuses.push(value); },
        className: '',
    };

    terminal.reconnectToExistingSession = async (session) => {
        calls.push(['reconnectToExistingSession', session && session.tmux_session]);
    };
    terminal.attemptReconnect = () => { calls.push(['attemptReconnect']); };

    const health = makeHealthFetch({ failCount, onCall });
    if (lazyWatch) {
        context.fetch = health.fetchImpl;
        context.navigator = { get onLine() { return online ? online.value : true; } };
    } else {
        terminal._restartWatch = new context.window.ServerRestartWatch(
            Object.assign({}, FAST_WATCH_OPTIONS, {
                fetchImpl: health.fetchImpl,
                onlineImpl: online ? (() => online.value) : undefined,
            })
        );
    }

    const fakeWs = { readyState: 1, close() {}, send() {} };
    terminal.ws = fakeWs;
    terminal.setupWebSocketHandlers();

    return {
        terminal,
        context,
        calls,
        statuses,
        lines,
        fetchCalls: health.calls,
        closeSocket(code) { fakeWs.onclose({ code }); },
        countOf(method) { return calls.filter((c) => c[0] === method).length; },
        assertNoCreate() {
            const created = calls.filter((c) => c[0] === 'createSession');
            assert.equal(created.length, 0,
                `expected zero createSession calls, got ${JSON.stringify(created)}`);
        },
    };
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('outage signature excludes 4400/4401/4404, includes ordinary close codes', async () => {
    const sb = makeSandbox();
    const Watch = sb.context.window.ServerRestartWatch;
    assert.equal(Watch.isOutageCloseCode(4400), false,
        '4400 (auth header present but empty) is an answered rejection, not an outage');
    assert.equal(Watch.isOutageCloseCode(4401), false);
    assert.equal(Watch.isOutageCloseCode(4404), false);
    assert.deepEqual([...Watch.EXCLUDED_CLOSE_CODES].sort(), [4400, 4401, 4404]);
    for (const code of [1000, 1001, 1006, 1011, 1012, 1013]) {
        assert.equal(Watch.isOutageCloseCode(code), true, `code ${code} should be an outage candidate`);
    }
    assert.equal(Watch.isOutageCloseCode(null), false);
    assert.equal(Watch.isOutageCloseCode(undefined), false);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('4400 close never triggers the health loop', async () => {
    const sb = makeSandbox({ failCount: Infinity });

    sb.closeSocket(4400);
    await waitFor(() => sb.countOf('attemptReconnect') > 0);

    assert.equal(sb.fetchCalls.length, 0, '4400 must not probe /health');
    assert.equal(sb.countOf('adoptSession'), 0);
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('server restart: polls health until it answers, then re-adopts by tmux name', async () => {
    const sb = makeSandbox({ failCount: 3 });

    sb.closeSocket(1006);
    await waitFor(() => sb.countOf('reconnectToExistingSession') > 0);

    assert.ok(sb.fetchCalls.length >= 4,
        `expected repeated health probes, got ${sb.fetchCalls.length}`);
    assert.equal(sb.fetchCalls[0], `${FAST_WATCH_OPTIONS.origin}/health`);

    const adopted = sb.calls.filter((c) => c[0] === 'adoptSession');
    assert.equal(adopted.length, 1, 'expected exactly one adoptSession call');
    assert.equal(adopted[0][1], TMUX_NAME, 'must re-adopt the SAME tmux name');

    assert.equal(sb.countOf('reconnectToExistingSession'), 1);
    assert.equal(sb.countOf('attemptReconnect'), 0,
        'the restart path must not fall back to the id-based retry loop');
    sb.assertNoCreate();

    const Watch = sb.context.window.ServerRestartWatch;
    assert.ok(sb.statuses.includes(Watch.STATUS.WAITING),
        `expected the waiting-for-server status, got ${JSON.stringify(sb.statuses)}`);
    assert.ok(sb.statuses.includes(Watch.STATUS.BACK),
        `expected the server-back status, got ${JSON.stringify(sb.statuses)}`);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('server still answering: falls back to the ordinary bounded retry', async () => {
    const sb = makeSandbox({ failCount: 0 });

    sb.closeSocket(1006);
    await waitFor(() => sb.countOf('attemptReconnect') > 0);

    assert.equal(sb.fetchCalls.length, 1, 'expected a single detection probe');
    assert.equal(sb.countOf('adoptSession'), 0, 'a live server needs no re-adopt');
    assert.equal(sb.countOf('attemptReconnect'), 1);
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('deliberately detached session is not revived', async () => {
    const sb = makeSandbox({ failCount: Infinity });
    sb.terminal.sessionActive = false;

    sb.closeSocket(1006);
    await new Promise((r) => setTimeout(r, 30));

    assert.equal(sb.fetchCalls.length, 0, 'must not probe health for an inactive session');
    assert.equal(sb.countOf('adoptSession'), 0, 'must not re-adopt a detached session');
    assert.equal(sb.countOf('reconnectToExistingSession'), 0);
    assert.equal(sb.countOf('attemptReconnect'), 0);
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('detach during the health wait aborts before re-adopting', async () => {
    let sb = null;
    sb = makeSandbox({
        failCount: Infinity,
        onCall(index) {
            if (index === 3 && sb) sb.terminal.sessionActive = false;
        },
    });

    sb.closeSocket(1006);
    await waitFor(() => sb.terminal._restartWatchActive === false && sb.fetchCalls.length >= 3);
    await new Promise((r) => setTimeout(r, 20));

    assert.equal(sb.countOf('adoptSession'), 0, 'must not re-adopt after the user detached');
    assert.equal(sb.countOf('reconnectToExistingSession'), 0);
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('health polling gives up at the ceiling without creating anything', async () => {
    const sb = makeSandbox({ failCount: Infinity });
    const Watch = sb.context.window.ServerRestartWatch;
    sb.terminal._restartWatch = new sb.context.window.ServerRestartWatch(
        Object.assign({}, FAST_WATCH_OPTIONS, {
            ceilingMs: 15,
            fetchImpl: sb.terminal._restartWatch._fetch,
        })
    );

    sb.closeSocket(1006);
    await waitFor(() => sb.statuses.includes(Watch.STATUS.UNREACHABLE));

    assert.equal(sb.countOf('adoptSession'), 0);
    assert.equal(sb.countOf('reconnectToExistingSession'), 0);
    sb.assertNoCreate();
    assert.equal(sb.terminal._restartWatchActive, false, 'the watch must not stay armed');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('4404 close still uses the existing by-name recovery, not the health loop', async () => {
    const sb = makeSandbox({ failCount: Infinity });
    let byName = 0;
    sb.terminal._attemptReconnectByName = async () => { byName++; };

    sb.closeSocket(4404);
    await waitFor(() => byName > 0);

    assert.equal(sb.fetchCalls.length, 0, '4404 must not trigger health polling');
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('adopt guard refuses a name this tab is not bound to, and refuses an empty name', async () => {
    const sb = makeSandbox();
    assert.throws(() => sb.terminal._assertAdoptTargetUnchanged('cloude_some-other-project'),
        /refusing to adopt/);
    assert.throws(() => sb.terminal._assertAdoptTargetUnchanged(''),
        /refusing to adopt without a tmux name/);
    sb.terminal._assertAdoptTargetUnchanged(TMUX_NAME);
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('server back but tmux session gone: ends the session, creates nothing', async () => {
    const sb = makeSandbox({ failCount: 2, attachable: [], live: [] });

    sb.closeSocket(1006);
    await waitFor(() => sb.calls.some(
        (c) => c[0] === 'dispatchEvent' && c[1] === 'cloude:primary-session-gone'));

    assert.equal(sb.countOf('adoptSession'), 0);
    assert.equal(sb.terminal.sessionActive, false, 'session must be marked ended');
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('a tab client (not the page owner) ends quietly: no session-destroyed', async () => {
    const sb = makeSandbox({ failCount: 2, attachable: [], live: [], pageOwner: false });

    sb.closeSocket(1006);
    await waitFor(() => sb.terminal.sessionActive === false);

    assert.equal(sb.countOf('adoptSession'), 0);
    assert.ok(!sb.calls.some((c) => c[0] === 'dispatchEvent'
        && (c[1] === 'session-destroyed' || c[1] === 'cloude:primary-session-gone')),
        'a tab client must never declare the page\'s session gone');
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('client offline: sends no probe, says so honestly, recovers when the link returns', async () => {
    const online = { value: false };
    const sb = makeSandbox({ failCount: 0, online });
    const Watch = sb.context.window.ServerRestartWatch;

    sb.closeSocket(1006);
    await waitFor(() => sb.statuses.includes(Watch.STATUS.OFFLINE));
    assert.equal(sb.fetchCalls.length, 0,
        'must not probe /health from a machine that has no network');
    assert.ok(!sb.statuses.includes(Watch.STATUS.WAITING),
        'must not claim the SERVER is silent while we are the ones offline');

    online.value = true;
    await waitFor(() => sb.countOf('reconnectToExistingSession') > 0);
    assert.ok(sb.fetchCalls.length >= 1, 'probes resume once the link is back');
    const adopted = sb.calls.filter((c) => c[0] === 'adoptSession');
    assert.equal(adopted.length, 1);
    assert.equal(adopted[0][1], TMUX_NAME);
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('offline time does not consume the server-unreachable ceiling', async () => {
    const sb = makeSandbox();
    const online = { value: false };
    const health = makeHealthFetch({ failCount: 0 });
    const watch = new sb.context.window.ServerRestartWatch(Object.assign({}, FAST_WATCH_OPTIONS, {
        ceilingMs: 20,
        offlineRecheckMs: 5,
        fetchImpl: health.fetchImpl,
        onlineImpl: () => online.value,
    }));

    setTimeout(() => { online.value = true; }, 120);
    const outcome = await watch.waitForServer({});

    assert.equal(outcome, sb.context.window.ServerRestartWatch.RESULT.UP,
        'an offline stretch longer than the ceiling must not report a timeout');
    assert.equal(health.calls.length, 1, 'exactly one probe, sent after the link returned');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('adopt guard blocks a re-adopt when the tab rebound during the wait', async () => {
    let sb = null;
    sb = makeSandbox({
        failCount: 3,
        onCall(index) {
            if (index === 2 && sb) {
                sb.terminal._currentSession = { id: 'sid-other', tmux_session: 'cloude_other-project' };
            }
        },
    });

    sb.closeSocket(1006);
    await waitFor(() => sb.countOf('attemptReconnect') > 0);

    assert.equal(sb.countOf('adoptSession'), 0,
        'must refuse to adopt once this tab is bound to a different session');
    assert.equal(sb.countOf('reconnectToExistingSession'), 0);
    sb.assertNoCreate();
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('lazy _serverRestartWatch() builds a real watch from ambient globals and memoizes it', async () => {
    const sb = makeSandbox({ failCount: 0, lazyWatch: true });
    const Watch = sb.context.window.ServerRestartWatch;

    assert.equal(sb.terminal._restartWatch, null, 'nothing pre-assigned');

    const built = sb.terminal._serverRestartWatch();
    assert.ok(built instanceof Watch, 'must build a real ServerRestartWatch');
    assert.equal(sb.terminal._serverRestartWatch(), built, 'must memoize one per Terminal');
    assert.equal(built.healthUrl(), `${FAST_WATCH_OPTIONS.origin}/health`,
        'origin must come from window.location');
    assert.equal(built.ceilingMs, Watch.DEFAULTS.ceilingMs, 'production defaults, not test tunables');
    assert.equal(built.firstDelayMs, Watch.DEFAULTS.firstDelayMs);
    assert.equal(built.isClientOffline(), false, 'reads the ambient navigator');
    assert.equal(await built.probe(), true, 'probes through the ambient global fetch');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
await test('a close with no pre-built watch constructs one and takes the live-server fallback', async () => {
    const sb = makeSandbox({ failCount: 0, lazyWatch: true });

    sb.closeSocket(1006);
    await waitFor(() => sb.countOf('attemptReconnect') > 0);

    assert.ok(sb.terminal._restartWatch, 'the close must have built the watch');
    assert.equal(sb.fetchCalls.length, 1, 'one detection probe through the real construction path');
    assert.equal(sb.fetchCalls[0], `${FAST_WATCH_OPTIONS.origin}/health`);
    assert.equal(sb.countOf('adoptSession'), 0);
    sb.assertNoCreate();
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    process.exit(1);
} else {
    console.log('ALL PASS');
    process.exit(0);
}
