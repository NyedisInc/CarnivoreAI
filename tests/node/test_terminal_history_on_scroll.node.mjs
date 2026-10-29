
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const CLIENT_JS = path.join(ROOT, 'client', 'js');
const ROWS = 40;

const captureOf = (n) => Array.from({ length: n }, (_, i) => 'L' + (i + 1)).join('\n') + '\n';

function makeTerm(held) {
    const buf = { baseY: held, viewportY: 0, type: 'normal', length: held + ROWS,
        getLine: (i) => ({ translateToString: () => (i < buf.length ? 'row ' + i : '') }) };
    const term = {
        cols: 100, rows: ROWS, options: { scrollback: 5000 },
        buffer: { active: buf }, writes: [], scrolls: [], listeners: [],
        onScroll(fn) { term.listeners.push(fn); return { dispose() {} }; },
        write(data, cb) {
            if (typeof data !== 'string') {
                term.writes.push(Buffer.from(data).toString('binary'));
                const lines = term.writes[term.writes.length - 1].split('\n').length - 1;
                buf.baseY = Math.max(0, lines - ROWS);
                buf.length = lines;
                buf.viewportY = buf.baseY;
            }
            if (typeof cb === 'function') cb();
        },
        scrollToLine(n) { buf.viewportY = n; term.scrolls.push(n); },
    };
    return term;
}

function realm({ available, held }) {
    const requests = [];
    const gate = [];
    const ctx = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        Promise, Number, Math, Object, Array, String, JSON, Uint8Array, Buffer, WeakMap, WeakSet,
        setTimeout, clearTimeout, Date,
        atob: (s) => Buffer.from(s, 'base64').toString('binary'),
        document: { querySelector: () => null },
        requestAnimationFrame(fn) { fn(); },
    };
    ctx.window = ctx;
    ctx.globalThis = ctx;
    vm.createContext(ctx);
    for (const f of ['terminal-reconnect-buffer.js', 'terminal-scrollback-paint.js',
        'terminal-history-load.js', 'terminal-history-scroll.js']) {
        vm.runInContext(fs.readFileSync(path.join(CLIENT_JS, f), 'utf8'), ctx, { filename: f });
    }
    ctx.API = {
        async getSession(id, o) {
            requests.push({ id, ...o });
            if (gate.length) await gate.shift();
            const n = Math.min(available, o.scrollbackLines || 0) + ROWS;
            return { initial_scrollback_b64: Buffer.from(captureOf(n), 'binary').toString('base64') };
        },
    };
    const term = makeTerm(held);
    const ctl = { term, _navToken: 1, _sessionId: () => 'ses_a', fitAddon: { fit() {} },
        _forceScrollToBottom() {} };
    ctx.TerminalController = ctl;
    return { ctx, ctl, term, requests, gate, S: ctx.TerminalHistoryScroll };
}

test('scroll to the top issues exactly one bounded fetch and prepends older lines in order', async () => {
    const r = realm({ available: 12000, held: 5000 });
    const out = await r.S.fetchOlder(r.ctl);
    assert.equal(out, 'painted');
    assert.equal(r.requests.length, 1);
    assert.equal(r.requests[0].scrollbackLines, 7500, 'held rows plus one step');
    assert.equal(r.requests[0].includeScrollback, true);
    assert.equal(r.requests[0].id, 'ses_a', 'the session id, never a derived name');
    const body = r.term.writes[0].split('\n').filter(Boolean);
    assert.equal(body.length, 7500 + ROWS);
    assert.deepEqual(body.slice(0, 3), ['L1', 'L2', 'L3'], 'oldest first, in order');
    assert.ok(r.term.options.scrollback >= 7500 + ROWS, 'cap raised to hold the fetched rows');
    assert.equal(r.term.buffer.active.baseY, 7500, 'the buffer now holds the older window');
});

test('a second scroll fetches the next older window and stops at the beginning', async () => {
    const r = realm({ available: 9000, held: 5000 });
    assert.equal(await r.S.fetchOlder(r.ctl), 'painted');
    r.term.buffer.active.viewportY = 0;
    assert.equal(await r.S.fetchOlder(r.ctl), 'painted');
    assert.deepEqual(r.requests.map((q) => q.scrollbackLines), [7500, 10000]);
    r.term.buffer.active.viewportY = 0;
    assert.equal(await r.S.fetchOlder(r.ctl), 'top', 'nothing older: the beginning');
    assert.equal(r.requests.length, 3);
    r.term.buffer.active.viewportY = 0;
    assert.equal(await r.S.fetchOlder(r.ctl), 'skipped');
    assert.equal(r.requests.length, 3, 'no request once the beginning is reached');
});

test('only one fetch is in flight, and a not-at-top scroll fetches nothing', async () => {
    const r = realm({ available: 12000, held: 5000 });
    let open; r.gate.push(new Promise((res) => { open = res; }));
    const first = r.S.fetchOlder(r.ctl);
    assert.equal(await r.S.fetchOlder(r.ctl), 'busy');
    open();
    assert.equal(await first, 'painted');
    r.term.buffer.active.viewportY = 10;
    assert.equal(await r.S.fetchOlder(r.ctl), 'skipped');
    assert.equal(r.requests.length, 1);
});

test('an answer that arrives after a session switch is discarded', async () => {
    const r = realm({ available: 12000, held: 5000 });
    let open; r.gate.push(new Promise((res) => { open = res; }));
    const pending = r.S.fetchOlder(r.ctl);
    r.ctl._navToken = 2;
    open();
    assert.equal(await pending, 'stale');
    assert.equal(r.term.writes.length, 0, 'nothing written into the pane that was switched to');
});

test('the alternate screen is never fetched into', async () => {
    const r = realm({ available: 12000, held: 5000 });
    r.term.buffer.active.type = 'alternate';
    assert.equal(await r.S.fetchOlder(r.ctl), 'skipped');
    assert.equal(r.requests.length, 0);
});

test('the request depth never exceeds the 50000 ceiling', () => {
    const r = realm({ available: 0, held: 0 });
    assert.equal(r.S.nextDepth(49000), 50000);
    assert.equal(r.S.nextDepth(50000), 50000);
});

test('the 5k cap is one named constant and the old 50000 is gone', () => {
    const src = fs.readFileSync(path.join(CLIENT_JS, 'terminal-client-factory.js'), 'utf8');
    assert.equal((src.match(/scrollback:\s*[\w]+/g) || []).length, 1);
    assert.match(src, /var SCROLLBACK_ROWS = 5000;/);
    assert.match(src, /scrollback:\s*SCROLLBACK_ROWS,/);
    assert.match(src, /SCROLLBACK_ROWS: SCROLLBACK_ROWS/);
    assert.doesNotMatch(src, /scrollback:\s*50000/);
});

test('every open path asks for the depth the buffer keeps, from the one constant', () => {
    const root = path.join(CLIENT_JS, '..', '..');
    const paths = [
        ['client/js/session-sidebar-clicks.js', 1],
        ['client/js/solo-window.js', 2],
        ['client/js/session-restart-return.js', 1],
        ['web/src/lib/launchpad/navigation.ts', 1],
        ['web/src/opscenter/cells/terminal-live/client.ts', 1],
    ];
    for (const [rel, want] of paths) {
        const src = fs.readFileSync(path.join(root, rel), 'utf8');
        const got = (src.match(/scrollbackLines:[^,\n]*SCROLLBACK_ROWS/g) || []).length;
        assert.equal(got, want, rel + ' sends scrollbackLines from SCROLLBACK_ROWS');
        assert.doesNotMatch(src, /scrollbackLines:\s*\d/, rel + ' has no literal depth');
    }
});

test('attach listens once and a scroll that reaches the top starts the fetch', async () => {
    const r = realm({ available: 12000, held: 5000 });
    r.S.attach(r.ctl);
    r.S.attach(r.ctl);
    assert.equal(r.term.listeners.length, 1);
    r.term.listeners[0]();
    await new Promise((res) => setTimeout(res, 20));
    assert.equal(r.requests.length, 1);
});
