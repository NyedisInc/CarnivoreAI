
import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const CLIENT_JS = path.join(ROOT, 'client', 'js');

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

function makeClock() {
    let now = 0;
    let nextId = 1;
    const timers = new Map();

    function flush() {
        return new Promise((resolve) => setImmediate(resolve));
    }

    return {
        get now() { return now; },
        setInterval(fn, ms) {
            const id = nextId++;
            timers.set(id, { fn, ms, due: now + ms, repeat: true });
            return id;
        },
        clearInterval(id) { timers.delete(id); },
        setTimeout(fn, ms) {
            const id = nextId++;
            timers.set(id, { fn, ms, due: now + (ms || 0), repeat: false });
            return id;
        },
        clearTimeout(id) { timers.delete(id); },
        async advance(ms) {
            const end = now + ms;
            for (;;) {
                let next = null;
                for (const [id, t] of timers) {
                    if (t.due <= end && (!next || t.due < next.t.due)) next = { id, t };
                }
                if (!next) break;
                now = next.t.due;
                if (next.t.repeat) next.t.due += next.t.ms;
                else timers.delete(next.id);
                next.t.fn();
                await flush();
            }
            now = end;
        },
        flush,
    };
}

function makeDocument() {
    const listeners = new Map();
    return {
        hidden: false,
        readyState: 'complete',
        documentElement: { hasAttribute: () => false, getAttribute: () => null },
        hasFocus: () => false,
        addEventListener(type, fn) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(fn);
        },
        removeEventListener(type, fn) {
            const list = listeners.get(type) || [];
            listeners.set(type, list.filter((f) => f !== fn));
        },
        dispatchEvent(evt) {
            for (const fn of listeners.get(evt.type) || []) fn(evt);
            return true;
        },
        listenerCount(type) { return (listeners.get(type) || []).length; },
        getElementById() { return null; },
        createElement() { return { innerHTML: '', className: '', id: '' }; },
    };
}

function makeContext(hidden) {
    const clock = makeClock();
    const document = makeDocument();
    document.hidden = hidden;
    const counts = { listSessions: 0, getAllToasts: 0 };
    const ctx = {
        console: { log() {}, warn() {}, error() {} },
        document,
        setInterval: clock.setInterval,
        clearInterval: clock.clearInterval,
        setTimeout: clock.setTimeout,
        clearTimeout: clock.clearTimeout,
        Date,
        Promise,
        API: {
            getToken() { return 'token'; },
            listSessions() {
                counts.listSessions++;
                return Promise.resolve([]);
            },
            getAllToasts() {
                counts.getAllToasts++;
                return Promise.resolve({ toasts: [] });
            },
        },
        ToastManager: { backfill() {}, reconcileOpen() {} },
        SessionSidebar: {
            isOpen: false,
            activeTmuxName() { return 'cloude_test'; },
        },
    };
    ctx.window = ctx;
    ctx.globalThis = ctx;
    vm.createContext(ctx);
    return { ctx, clock, document, counts };
}

function load(ctx, files) {
    for (const file of files) {
        const src = fs.readFileSync(path.join(CLIENT_JS, file), 'utf8');
        vm.runInContext(src, ctx, { filename: file });
    }
}

const POLLERS = ['toast-global-poll.js', 'session-header-led.js'];
const MINUTE_MS = 60000;

async function runMinute(hidden) {
    const h = makeContext(hidden);
    load(h.ctx, POLLERS);
    await h.clock.flush();
    h.counts.listSessions = 0;
    h.counts.getAllToasts = 0;
    await h.clock.advance(MINUTE_MS);
    return h;
}

// ------------------------------------------------------------------ //
// ------------------------------------------------------------------ //

await test('negative control: a visible tab still polls at 12 and 6 per minute', async () => {
    const { counts } = await runMinute(false);
    assert.equal(counts.listSessions, 12, 'header LED fallback poll, 5s cadence');
    assert.equal(counts.getAllToasts, 6, 'global toast poll, 10s cadence');
});

await test('a hidden tab issues zero HTTP requests over a simulated minute', async () => {
    const { counts } = await runMinute(true);
    assert.equal(counts.listSessions, 0,
        'GET /sessions/list still polled while hidden');
    assert.equal(counts.getAllToasts, 0,
        'GET /sessions/toasts still polled while hidden');
});

await test('becoming visible performs exactly one authoritative re-read per poller', async () => {
    const h = await runMinute(true);
    h.document.hidden = false;
    h.document.dispatchEvent({ type: 'visibilitychange' });
    assert.equal(h.counts.listSessions, 1, 'header LED did not re-read on return');
    assert.equal(h.counts.getAllToasts, 1, 'toast poll did not re-read on return');
    await h.clock.flush();
    assert.equal(h.counts.listSessions, 1, 'header LED re-read more than once');
    assert.equal(h.counts.getAllToasts, 1, 'toast poll re-read more than once');
});

await test('a visibilitychange to HIDDEN triggers no read', async () => {
    const h = await runMinute(false);
    const before = { ...h.counts };
    h.document.hidden = true;
    h.document.dispatchEvent({ type: 'visibilitychange' });
    await h.clock.flush();
    assert.deepEqual(h.counts, before);
});


await test('a tab hidden AFTER the pollers started issues zero HTTP in the next minute', async () => {
    const h = await runMinute(false);
    assert.equal(h.counts.listSessions, 12, 'harness did not observe the visible minute');
    assert.equal(h.counts.getAllToasts, 6, 'harness did not observe the visible minute');
    h.document.hidden = true;
    h.document.dispatchEvent({ type: 'visibilitychange' });
    h.counts.listSessions = 0;
    h.counts.getAllToasts = 0;
    await h.clock.advance(MINUTE_MS);
    assert.equal(h.counts.listSessions, 0,
        'the header LED cached its gate at start() instead of reading each tick');
    assert.equal(h.counts.getAllToasts, 0,
        'the toast poll cached its gate at start() instead of reading each tick');
});

await test('the header LED registers ONE visibility listener across start/stop/start', async () => {
    const h = makeContext(false);
    load(h.ctx, POLLERS);
    const led = h.ctx.window.SessionHeaderLed;
    const after = h.document.listenerCount('visibilitychange');
    led.stop();
    led.start();
    led.start();
    assert.equal(h.document.listenerCount('visibilitychange'), after,
        'a second start() registered a second listener');
});

await test('the gates never touch requestAnimationFrame (gotcha 9)', async () => {
    const DRAWER = path.join(ROOT, 'web', 'src', 'lib', 'drawer');
    for (const file of POLLERS) {
        const src = fs.readFileSync(path.join(CLIENT_JS, file), 'utf8');
        assert.ok(!src.includes('requestAnimationFrame'),
            `${file} gates on a frame, which a hidden tab never runs`);
    }
    for (const file of ['controller.ts', 'boot.ts']) {
        const src = fs.readFileSync(path.join(DRAWER, file), 'utf8');
        assert.ok(!src.includes('requestAnimationFrame'),
            `${file} gates on a frame, which a hidden tab never runs`);
    }
    const sidebar = fs.readFileSync(path.join(DRAWER, 'controller.ts'), 'utf8');
    const startPoll = sidebar.slice(sidebar.indexOf('_startPoll(): void {'), sidebar.indexOf('_stopPoll(): void {'));
    assert.ok(startPoll.length > 20, 'the poll was not found where this reads it');
    assert.ok(startPoll.includes('document.hidden'), '_startPoll does not read document.hidden');
    assert.ok(!startPoll.includes('requestAnimationFrame'));
});

// ------------------------------------------------------------------ //
// ------------------------------------------------------------------ //

function makeSidebar(hidden) {
    const h = makeContext(hidden);
    delete h.ctx.SessionSidebar;
    installCloudeWeb(h.ctx);
    const sidebar = h.ctx.window.SessionSidebar;
    const calls = { fetch: 0 };
    sidebar._fetchAndRender = function () {
        calls.fetch++;
        return Promise.resolve();
    };
    return { h, sidebar, calls };
}

await test('sidebar negative control: an open panel in a visible tab polls 12 times a minute', async () => {
    const { h, sidebar, calls } = makeSidebar(false);
    sidebar.isOpen = true;
    sidebar._startPoll();
    await h.clock.advance(MINUTE_MS);
    assert.equal(calls.fetch, 12);
});

await test('sidebar: an open panel in a hidden tab polls zero times a minute', async () => {
    const { h, sidebar, calls } = makeSidebar(true);
    sidebar.isOpen = true;
    sidebar._startPoll();
    await h.clock.advance(MINUTE_MS);
    assert.equal(calls.fetch, 0, 'sidebar poll still fetched while hidden');
});

await test('sidebar: returning to visible re-reads once through refreshNow while open', async () => {
    const { h, sidebar, calls } = makeSidebar(true);
    sidebar.isOpen = true;
    sidebar._startPoll();
    await h.clock.advance(MINUTE_MS);
    h.document.hidden = false;
    h.document.dispatchEvent({ type: 'visibilitychange' });
    await h.clock.flush();
    assert.equal(calls.fetch, 1, 'no authoritative re-read on return');
});

await test('sidebar: returning to visible with the panel closed reads nothing', async () => {
    const { h, sidebar, calls } = makeSidebar(true);
    sidebar.isOpen = false;
    await h.clock.advance(MINUTE_MS);
    h.document.hidden = false;
    h.document.dispatchEvent({ type: 'visibilitychange' });
    await h.clock.flush();
    assert.equal(calls.fetch, 0,
        'a closed panel must not render rows the user has not asked for');
});

await test('a sidebar hidden AFTER _startPoll issues zero fetches in the next minute', async () => {
    const { h, sidebar, calls } = makeSidebar(false);
    sidebar.isOpen = true;
    sidebar._startPoll();
    await h.clock.advance(MINUTE_MS);
    assert.equal(calls.fetch, 12, 'harness did not observe the visible minute');
    h.document.hidden = true;
    h.document.dispatchEvent({ type: 'visibilitychange' });
    calls.fetch = 0;
    await h.clock.advance(MINUTE_MS);
    assert.equal(calls.fetch, 0,
        '_startPoll cached its gate instead of reading document.hidden each tick');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
