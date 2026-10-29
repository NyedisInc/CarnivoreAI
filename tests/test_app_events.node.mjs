
import { strict as assert } from 'node:assert';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(here, '..');
const CLIENT = path.join(ROOT, 'client', 'js');
const MODULE = path.join(CLIENT, 'app-events.js');
const RECOVERY_MODULE = path.join(CLIENT, 'socket-auth-recovery.js');

function load() {
    delete require.cache[require.resolve(MODULE)];
    delete require.cache[require.resolve(RECOVERY_MODULE)];
    delete globalThis.AppEvents;
    delete globalThis.SessionSidebar;
    delete globalThis.Launchpad;
    delete globalThis.PreferencesTransport;
    delete globalThis.ToastManager;
    delete globalThis.API;
    delete globalThis.SocketAuthRecovery;
    require(RECOVERY_MODULE);
    return require(MODULE);
}

function spies() {
    const calls = [];
    globalThis.SessionSidebar = { refreshNow: () => calls.push('sidebar') };
    globalThis.Launchpad = { loadRunningSessions: () => calls.push('launchpad') };
    globalThis.PreferencesTransport = {
        CHANGED: 'preferences.changed',
        refreshOnReconnect: () => calls.push('preferences-refresh'),
        handleFrame: (f) => { calls.push('preferences-frame:' + f.revision); return true; },
    };
    globalThis.ToastManager = {
        add: (t) => calls.push('toast-add:' + t.id),
        dismiss: (id) => calls.push('toast-dismiss:' + id),
    };
    return calls;
}

test('hello triggers an authoritative refresh of everything', () => {
    const events = load();
    const calls = spies();
    assert.equal(events.handleFrame({ type: 'events.hello', client_id: 'evt_1' }), true);
    assert.deepEqual(calls, ['preferences-refresh', 'sidebar', 'launchpad']);
});

test('a status notice re-reads rather than patching the row locally', () => {
    const events = load();
    const calls = spies();
    events.handleFrame({
        type: 'session.status', session_id: 'ses_b', activity_status: 'question',
    });
    assert.deepEqual(calls, ['sidebar', 'launchpad']);
});

test('a structural notice re-reads the list', () => {
    const events = load();
    const calls = spies();
    events.handleFrame({ type: 'sessions.changed', reason: 'created' });
    assert.deepEqual(calls, ['sidebar', 'launchpad']);
});

test('toast frames go to the module that already owns toast cards', () => {
    const events = load();
    const calls = spies();
    events.handleFrame({ type: 'toast.new', toast: { id: 't1' } });
    events.handleFrame({ type: 'toast.ack', toast_id: 't1' });
    assert.deepEqual(calls, ['toast-add:t1', 'toast-dismiss:t1']);
});

test('a preferences frame goes to the existing transport, not a second copy', () => {
    const events = load();
    const calls = spies();
    events.handleFrame({ type: 'preferences.changed', revision: 7 });
    assert.deepEqual(calls, ['preferences-frame:7']);
});

test('an unknown frame type is ignored and does not force a re-read', () => {
    const events = load();
    const calls = spies();
    assert.equal(events.handleFrame({ type: 'something.newer' }), false);
    assert.deepEqual(calls, []);
});

test('every branch survives the modules it pokes being absent', () => {
    const events = load();
    assert.doesNotThrow(() => {
        events.handleFrame({ type: 'events.hello' });
        events.handleFrame({ type: 'sessions.changed' });
        events.handleFrame({ type: 'toast.new', toast: { id: 'x' } });
        events.handleFrame({ type: 'toast.ack', toast_id: 'x' });
    });
});

test('an overflow close reconnects at once and any other close backs off with jitter', () => {
    const events = load();
    events._state.attempts = 1;
    assert.equal(events.backoffFor(events.OVERFLOW_CLOSE_CODE), 0);
    const within = (value, center, tolerance) =>
        value >= center * (1 - tolerance) && value <= center * (1 + tolerance);
    assert.ok(within(events.backoffFor(1006), 1000, 0.2), events.backoffFor(1006));
    events._state.attempts = 3;
    assert.ok(within(events.backoffFor(1006), 4000, 0.2));
    events._state.attempts = 99;
    assert.ok(events.backoffFor(1006) <= 30000 && events.backoffFor(1006) >= 24000);
});

test('the close code matches the server constant exactly', () => {
    const events = load();
    const server = fs.readFileSync(
        path.join(ROOT, 'src', 'core', 'bounded_stream.py'), 'utf8');
    const match = server.match(/^OVERFLOW_CLOSE_CODE\s*=\s*(\d+)/m);
    assert.ok(match, 'server no longer declares OVERFLOW_CLOSE_CODE');
    assert.equal(events.OVERFLOW_CLOSE_CODE, Number(match[1]));
});

function makeSocketFactory(sockets) {
    return function () {
        const ws = { readyState: 0, onopen: null, onmessage: null, onerror: null, onclose: null, close() {} };
        sockets.push(ws);
        return ws;
    };
}

test('a close with no onopen refreshes the token exactly once, then reconnects with it', async () => {
    const events = load();
    const sockets = [];
    let refreshCalls = 0;
    globalThis.API = {
        getToken: () => 'stale-token',
        openWebSocket: makeSocketFactory(sockets),
        _singleFlightRefresh: async () => { refreshCalls += 1; return true; },
    };
    events.start();
    assert.equal(sockets.length, 1, 'did not attempt an initial connect');
    sockets[0].onclose({ code: 1006, reason: '' });
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(refreshCalls, 1, 'must refresh exactly once for this episode');
    assert.equal(sockets.length, 2, 'must reconnect once the refresh rotated the token');
    events.stop();
});

test('a failed refresh after an unopened close stops the loop instead of retrying forever', async () => {
    const events = load();
    const sockets = [];
    let refreshCalls = 0;
    let signalledUnauthorized = false;
    globalThis.API = {
        getToken: () => 'stale-token',
        openWebSocket: makeSocketFactory(sockets),
        _singleFlightRefresh: async () => { refreshCalls += 1; return false; },
        handleUnauthorized: () => { signalledUnauthorized = true; },
    };
    events.start();
    assert.equal(sockets.length, 1);
    sockets[0].onclose({ code: 1006, reason: '' });
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(refreshCalls, 1, 'refresh runs exactly once, not once per retry');
    assert.equal(sockets.length, 1, 'a dead refresh token must not keep opening new sockets');
    assert.equal(events._state.stopped, true, 'the loop must stand down rather than spin forever');
    assert.ok(signalledUnauthorized, 'a dead refresh token must surface the signed-out state');
});

test('a token refused again after the re-auth parks the socket until a new token appears', async () => {
    const listeners = {};
    globalThis.addEventListener = (type, fn) => { (listeners[type] ||= []).push(fn); };
    const events = load();
    const sockets = [];
    const timers = [];
    const realSetTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (fn, ms) => { timers.push(ms); return realSetTimeout(() => {}, 0); };
    let token = 'dead-token';
    try {
        globalThis.API = {
            getToken: () => token,
            openWebSocket: makeSocketFactory(sockets),
            _singleFlightRefresh: async () => true,
        };
        events.start();
        sockets[0].onclose({ code: 1006, reason: '' });
        await new Promise((resolve) => setImmediate(resolve));
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(sockets.length, 2, 'one reconnect after the re-auth');
        sockets[1].onclose({ code: 4401, reason: 'invalid token' });
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(events._state.parked, true, 'refused twice on one token: parked');
        assert.deepEqual(timers.filter((ms) => ms > 0), [], 'a parked socket arms no retry timer');
        events.start();
        assert.equal(sockets.length, 2, 'the refused token is never presented again');
        token = 'fresh-token';
        for (const fn of listeners.storage ?? []) fn({ key: 'claude_tunnel_token' });
        assert.equal(sockets.length, 3, 'a new token from another window reconnects at once');
    } finally {
        globalThis.setTimeout = realSetTimeout;
        delete globalThis.addEventListener;
        events.stop();
    }
});

test('a page with no refresh path parks on a refused token instead of retrying it', () => {
    const events = load();
    delete globalThis.SocketAuthRecovery;
    const sockets = [];
    globalThis.API = { getToken: () => 'dead-token', openWebSocket: makeSocketFactory(sockets) };
    events.start();
    sockets[0].onclose({ code: 1006, reason: '' });
    assert.equal(events._state.parked, true);
    assert.equal(events._state.timer, null, 'no backoff timer: the old loop retried every ~31 s');
    events.stop();
});

test('start refuses to open a socket with no credential to present', () => {
    const events = load();
    let opened = 0;
    globalThis.API = {
        getToken: () => null,
        openWebSocket: () => { opened += 1; return {}; },
    };
    events.start();
    assert.equal(opened, 0);
    events.stop();
});

test('start opens the events path through the app API, reusing its auth', () => {
    const events = load();
    const opens = [];
    globalThis.API = {
        getToken: () => 'a-token',
        openWebSocket: (sessionId, urlPath) => {
            opens.push([sessionId, urlPath]);
            return {};
        },
    };
    events.start();
    assert.deepEqual(opens, [[null, '/ws/events']]);
    events.stop();
});

test('the page actually loads and starts the channel', () => {
    const html = fs.readFileSync(path.join(ROOT, 'client', 'index.html'), 'utf8');
    assert.ok(html.includes('/static/js/app-events.js'),
        'app-events.js is not loaded by index.html');
    assert.match(html, /<script type="module" src="\/static\/dist\/app\.js"><\/script>/,
        'the bundle that publishes window.SessionSidebar is not loaded as a module');

    const app = fs.readFileSync(path.join(CLIENT, 'app.js'), 'utf8');
    assert.ok(app.includes('AppEvents.start()'),
        'nothing starts the event channel');
    const initAt = app.indexOf('async _initAuthenticatedState()');
    const startAt = app.indexOf('AppEvents.start()');
    assert.ok(initAt !== -1 && startAt > initAt && startAt - initAt < 1200,
        'AppEvents.start() is not inside _initAuthenticatedState');
});

test('the sidebar exposes the public refresh the channel pokes', () => {
    const DRAWER = path.join(ROOT, 'web', 'src', 'lib', 'drawer');
    const mod = fs.readFileSync(path.join(DRAWER, 'controller.ts'), 'utf8');
    const at = mod.indexOf('refreshNow(): Promise<void> | undefined {');
    assert.ok(at !== -1, 'the controller has no refreshNow');
    const body = mod.slice(at, mod.indexOf('\n    }', at));
    assert.ok(body.includes('this._fetchAndRender()'));
    assert.ok(body.includes('if (!this.isOpen && !railed) return undefined;'),
        'refreshNow must not render into a closed sidebar with no rail up');

    const boot = fs.readFileSync(path.join(DRAWER, 'boot.ts'), 'utf8');
    assert.ok(boot.includes('root.SessionSidebar = ctrl'), 'the bundle does not publish window.SessionSidebar');
});

test('nothing here removed a poll', () => {
    const sidebar = fs.readFileSync(path.join(ROOT, 'web', 'src', 'lib', 'drawer', 'controller.ts'), 'utf8');
    assert.ok(/POLL_MS\(\)\s*\{\s*return 5000;/.test(sidebar)
        || sidebar.includes('return 5000;'),
        'the five second reconciliation poll is gone');
    assert.ok(sidebar.includes('_startPoll()'), 'the poll timer is gone');
});
