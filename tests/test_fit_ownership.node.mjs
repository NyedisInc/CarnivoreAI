// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const LAYOUT_SRC = read('client/js/terminal-layout.js');
const SETTLE_SRC = read('client/js/terminal-resize-settle.js');

function makeRealm() {
    const timers = [];
    const counts = { guarded: 0, raw: 0, ships: [], enforce: 0 };

    const controller = {
        term: { cols: 100, rows: 40 },
        fitAddon: { fit() { counts.raw += 1; } },
        lastSentCols: 0,
        lastSentRows: 0,
        sendResize(reason) { counts.ships.push(reason); },
    };

    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
        clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].fn = null; },
        document: { getElementById: () => null, querySelector: () => null, body: { classList: { contains: () => false } } },
        addEventListener() {}, removeEventListener() {},
        ResizeObserver: function () { this.observe = () => {}; this.disconnect = () => {}; },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(SETTLE_SRC, sandbox, { filename: 'terminal-resize-settle.js' });
    vm.runInContext(LAYOUT_SRC, sandbox, { filename: 'terminal-layout.js' });

    sandbox.window.TerminalMetrics = {
        guardedFit() { counts.guarded += 1; return { fitted: true, reason: 'ok' }; },
        enforceWidthFit() { counts.enforce += 1; return { changed: false }; },
        describeCellMetrics: () => '',
    };
    sandbox.window.TerminalLayout.install(controller);

    const run = () => {
        const due = timers.splice(0, timers.length);
        for (const t of due) if (t.fn) t.fn();
    };
    return { window: sandbox.window, run, controller, counts };
}


test('a window resize produces exactly ONE measurement and ONE ship', () => {
    const { window: w, run, counts } = makeRealm();
    w.TerminalLayout.requestFit('window.resize');
    run();
    assert.equal(counts.guarded, 1, 'one layout change, one measurement');
    assert.equal(counts.raw, 0, 'and it went through the guard, not around it');
    assert.deepEqual(counts.ships, ['window.resize']);
});

test('a sidebar pin toggle produces exactly ONE measurement and ONE ship', () => {
    const { window: w, run, counts } = makeRealm();
    w.TerminalLayout.requestFit('sidebar-pin');
    run();
    assert.equal(counts.guarded, 1);
    assert.deepEqual(counts.ships, ['sidebar-pin']);
});

test('THE CASE THE OWNER EXISTS FOR: several sources for one change still fit once', () => {
    const { window: w, run, counts } = makeRealm();
    w.TerminalLayout.requestFit('sidebar-pin');
    w.TerminalLayout.requestFit('ResizeObserver');
    w.TerminalLayout.requestFit('ResizeObserver');
    w.TerminalLayout.requestFit('ResizeObserver');
    run();
    assert.equal(counts.guarded, 1,
        `one layout change took ${counts.guarded} measurements`);
    assert.equal(counts.ships.length, 1,
        `one layout change sent ${counts.ships.length} resizes to the pane`);
});

test('an UNANNOUNCED change settling back to the pane\'s own grid ships nothing', () => {
    const { window: w, run, controller, counts } = makeRealm();
    controller.lastSentCols = 100;
    controller.lastSentRows = 40;
    w.TerminalLayout.requestFit('ResizeObserver');
    run();
    assert.equal(counts.guarded, 1, 'it is still measured');
    assert.deepEqual(counts.ships, [], 'and deliberately not shipped');
});

test('POSITIVE CONTROL: an ANNOUNCED change at identical dims still ships', () => {
    const { window: w, run, controller, counts } = makeRealm();
    controller.lastSentCols = 100;
    controller.lastSentRows = 40;
    w.TerminalLayout.requestFit('window.resize');
    run();
    assert.deepEqual(counts.ships, ['window.resize']);
});

test('A REFUSED MEASUREMENT SHIPS NOTHING AND KEEPS THE LAST GOOD GRID', () => {
    const { window: w, run, counts } = makeRealm();
    w.TerminalMetrics.guardedFit = () => {
        counts.guarded += 1;
        return { fitted: false, reason: 'xterm-css-not-applied' };
    };
    w.TerminalLayout.requestFit('window.resize');
    run();
    assert.deepEqual(counts.ships, [],
        'a grid nobody could measure must never reach tmux');
    assert.equal(counts.raw, 0, 'and it must not fall back to an unguarded fit');
});

test('every ship carries a SOURCE NAME, never a bare call', () => {
    const { window: w, run, counts } = makeRealm();
    for (const source of ['window.resize', 'orientationchange', 'handshake']) {
        w.TerminalLayout.requestFit(source);
        run();
    }
    assert.deepEqual(counts.ships, ['window.resize', 'orientationchange', 'handshake']);
    for (const s of counts.ships) {
        assert.ok(s && s !== 'unknown', 'an unnamed resize cannot be diagnosed later');
    }
});


test('NO CALL SITE MEASURES OUTSIDE THE GUARD, across the whole client', () => {
    const allowed = new Map([
        ['client/js/terminal-metrics.js', 2],
        ['client/js/terminal-layout.js', 1],
        ['client/js/terminal-readiness.js', 1],
        ['client/js/terminal-scrollback-paint.js', 1],
    ]);
    const dir = path.join(ROOT, 'client/js');
    const offenders = [];
    for (const name of fs.readdirSync(dir)) {
        if (!name.endsWith('.js')) continue;
        const rel = 'client/js/' + name;
        const src = fs.readFileSync(path.join(dir, name), 'utf8');
        const hits = (src.match(/\bfitAddon(\s*&&\s*[\w.]+)?\.fit\(\)/g) || []).length;
        const budget = allowed.get(rel) || 0;
        if (hits > budget) offenders.push(`${rel}: ${hits} raw fits, ${budget} allowed`);
    }
    assert.deepEqual(offenders, [],
        'a raw fitAddon.fit() measures the character cell without asking '
        + 'whether xterm.css applied; route it through '
        + 'TerminalMetrics.guardedFit or TerminalLayout.requestFit');
});

test('the home screen no longer reaches into the terminal controller to fit', () => {
    const src = read('web/src/lib/launchpad/nav-host.ts')
        .split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n');
    assert.ok(!/fitAddon/.test(src),
        'nav-host.ts must ask TerminalMetrics for the grid, not fit it itself');
    assert.ok(src.includes('currentGrid()'),
        'the rejoin pre-fit must read the grid through the metrics owner');
    assert.equal((src.match(/currentGrid\(\)/g) || []).length, 2,
        'both terminalDims() and browserPrepareTerminal() read the grid, and '
        + 'both must read it the same way');
});

test('the rejoin path no longer awaits a bare animation frame', () => {
    const src = read('web/src/lib/launchpad/nav-host.ts');
    const fn = src.slice(src.indexOf('function twoFrames('));
    const body = fn.slice(0, fn.indexOf('\n}'));
    assert.ok(/setTimeout\(/.test(body),
        'the wait must be raced against a timer, or a tab the browser is not '
        + 'painting never resolves it and the rejoin is cancelled, not delayed');
    assert.ok(/requestAnimationFrame/.test(body),
        'and it must still prefer the frame when there is one');
});

test('every pane resize leaves through sendResize, and each names its source', () => {
    const sites = [];
    const dir = path.join(ROOT, 'client/js');
    for (const name of fs.readdirSync(dir)) {
        if (!name.endsWith('.js')) continue;
        const src = fs.readFileSync(path.join(dir, name), 'utf8')
            .split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n');
        for (const m of src.matchAll(/\.sendResize\(([^)]*)\)/g)) {
            if (/^\s*source\b/.test(m[1])) continue;
            sites.push(`client/js/${name}: sendResize(${m[1]})`);
        }
    }
    assert.equal(sites.length, 6,
        `${sites.length} ship sites: ${sites.join(' | ')}. The coalescer, `
        + 'the two handshake-shaped ones, the two visibility ones and the '
        + 'component tab withdrawal are the whole set; a seventh needs a '
        + 'reason written down');
    for (const s of sites) {
        assert.ok(/sendResize\(\s*('[a-z.\-]+'|reason)/.test(s),
            `a ship with no source name: ${s}`);
    }
});
