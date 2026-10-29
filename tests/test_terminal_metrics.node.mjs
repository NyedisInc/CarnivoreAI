
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { TerminalProvider } from '../web/src/lib/terminal-provider/provider.ts';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readClientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

function readClientCss(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'css', name), 'utf8');
}

let passes = 0;
let failures = 0;
const queue = [];

function test(name, fn) {
    queue.push([name, fn]);
}

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

function settle(ms) {
    return new Promise((r) => setTimeout(r, ms));
}


function makeSandbox(options = {}) {
    const {
        position = 'relative',
        proposal = { cols: 80, rows: 24 },
        hasPropose = true,
    } = options;

    const fits = [];
    const wire = [];
    const listeners = { window: {}, visualViewport: {} };
    let observerCb = null;

    const xtermEl = { className: 'xterm' };
    const termEl = { id: 'terminal', clientWidth: 640, clientHeight: 384 };

    const state = { position, proposal };

    const controller = {
        term: { cols: 80, rows: 24 },
        fitAddon: {
            fit() { fits.push('fit'); },
        },
        lastSentCols: null,
        lastSentRows: null,
        sendResize(reason) {
            const { cols, rows } = controller.term;
            if (cols === controller.lastSentCols && rows === controller.lastSentRows) return;
            wire.push({ cols, rows, reason });
            controller.lastSentCols = cols;
            controller.lastSentRows = rows;
        },
    };
    if (hasPropose) {
        controller.fitAddon.proposeDimensions = () => state.proposal;
    }

    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        setTimeout,
        clearTimeout,
        Promise,
        Number,
        Math,
        Date,
        document: {
            querySelector(sel) {
                if (sel === '.xterm') return xtermEl;
                return null;
            },
            getElementById(id) { return id === 'terminal' ? termEl : null; },
            fonts: { ready: Promise.resolve() },
        },
        ResizeObserver: class {
            constructor(cb) { observerCb = cb; }
            observe() {}
        },
    };
    sandbox.window = sandbox;
    sandbox.getComputedStyle = () => ({ position: state.position });
    sandbox.addEventListener = (name, cb) => { listeners.window[name] = cb; };

    sandbox.TerminalProvider = TerminalProvider;

    vm.createContext(sandbox);
    vm.runInContext(readClientJs('terminal-metrics.js'), sandbox);
    vm.runInContext(readClientJs('terminal-layout.js'), sandbox);

    return { sandbox, controller, fits, wire, state, listeners, observerCb: () => observerCb };
}


test('proposalIsSane accepts a normal grid', () => {
    const { sandbox } = makeSandbox();
    const r = sandbox.TerminalMetrics.proposalIsSane({ cols: 80, rows: 24 });
    assert.equal(r.ok, true);
});

test('proposalIsSane rejects a missing proposal', () => {
    const { sandbox } = makeSandbox();
    assert.equal(sandbox.TerminalMetrics.proposalIsSane(undefined).ok, false);
    assert.equal(sandbox.TerminalMetrics.proposalIsSane(null).reason, 'no-proposal');
});

test('proposalIsSane rejects NaN dimensions', () => {
    const { sandbox } = makeSandbox();
    const r = sandbox.TerminalMetrics.proposalIsSane({ cols: NaN, rows: 24 });
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'non-finite');
});

test('proposalIsSane rejects a collapsed grid', () => {
    const { sandbox } = makeSandbox();
    const r = sandbox.TerminalMetrics.proposalIsSane({ cols: 0, rows: 0 });
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'too-small');
});

test('proposalIsSane rejects the sub-pixel-cell blowup', () => {
    const { sandbox } = makeSandbox();
    const r = sandbox.TerminalMetrics.proposalIsSane({ cols: 21000, rows: 9000 });
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'too-large');
});

test('a phone-sized grid is accepted, not mistaken for a failure', () => {
    const { sandbox } = makeSandbox();
    assert.equal(sandbox.TerminalMetrics.proposalIsSane({ cols: 45, rows: 30 }).ok, true);
});


test('xterm.css counted as applied when .xterm is positioned', () => {
    const { sandbox } = makeSandbox({ position: 'relative' });
    assert.equal(sandbox.TerminalMetrics.xtermStylesheetApplied(), true);
});

test('xterm.css counted as MISSING when .xterm is static', () => {
    const { sandbox } = makeSandbox({ position: 'static' });
    assert.equal(sandbox.TerminalMetrics.xtermStylesheetApplied(), false);
});


test('guardedFit fits when the stylesheet applied and the proposal is sane', () => {
    const { sandbox, controller, fits } = makeSandbox();
    const r = sandbox.TerminalMetrics.guardedFit(controller);
    assert.equal(r.fitted, true);
    assert.equal(fits.length, 1);
});

test('guardedFit refuses to fit with xterm.css missing', () => {
    const { sandbox, controller, fits } = makeSandbox({ position: 'static' });
    const r = sandbox.TerminalMetrics.guardedFit(controller);
    assert.equal(r.fitted, false);
    assert.equal(r.reason, 'xterm-css-not-applied');
    assert.equal(fits.length, 0, 'must not measure at all');
});

test('guardedFit refuses to fit on an insane proposal', () => {
    const { sandbox, controller, fits } = makeSandbox({ proposal: { cols: 1, rows: 1 } });
    assert.equal(sandbox.TerminalMetrics.guardedFit(controller).fitted, false);
    assert.equal(fits.length, 0);
});

test('guardedFit still fits when the addon has no proposeDimensions', () => {
    const { sandbox, controller, fits } = makeSandbox({ hasPropose: false });
    const r = sandbox.TerminalMetrics.guardedFit(controller);
    assert.equal(r.fitted, true);
    assert.equal(r.reason, 'unvalidated');
    assert.equal(fits.length, 1);
});


test('a refused fit ships NOTHING to tmux', async () => {
    const { sandbox, controller, wire } = makeSandbox({ position: 'static' });
    sandbox.TerminalLayout.install(controller);
    sandbox.TerminalLayout.requestFit('test', { immediate: true });
    await settle(20);
    assert.equal(wire.length, 0, 'no pty_resize may be sent on a refused fit');
});

test('a good fit does ship to tmux', async () => {
    const { sandbox, controller, wire } = makeSandbox();
    controller.fitAddon.fit = () => { controller.term.cols = 45; controller.term.rows = 30; };
    sandbox.TerminalLayout.install(controller);
    sandbox.TerminalLayout.requestFit('test', { immediate: true });
    await settle(20);
    assert.equal(wire.length, 1);
    assert.deepEqual({ cols: wire[0].cols, rows: wire[0].rows }, { cols: 45, rows: 30 });
});

test('a refused fit retries and succeeds once the stylesheet lands', async () => {
    const { sandbox, controller, wire, state } = makeSandbox({ position: 'static' });
    controller.fitAddon.fit = () => { controller.term.cols = 45; controller.term.rows = 30; };
    sandbox.TerminalLayout.install(controller);
    sandbox.TerminalLayout.requestFit('test', { immediate: true });
    await settle(20);
    assert.equal(wire.length, 0, 'nothing shipped while the stylesheet is missing');
    state.position = 'relative';
    await settle(400);
    assert.equal(wire.length, 1, 'the retry must eventually ship the real grid');
    assert.equal(wire[0].cols, 45);
});

test('retries are bounded so a broken page cannot spin forever', () => {
    const { sandbox } = makeSandbox();
    assert.ok(Number.isFinite(sandbox.TerminalLayout.MAX_FIT_RETRIES));
    assert.ok(sandbox.TerminalLayout.MAX_FIT_RETRIES > 0);
    assert.ok(sandbox.TerminalLayout.MAX_FIT_RETRIES <= 20);
});


test('the mono font stack asks for ui-monospace, not bare SF Mono', () => {
    const css = readClientCss('styles.css');
    const m = css.match(/--font-mono:\s*([^;]+);/);
    assert.ok(m, '--font-mono must be defined');
    assert.ok(/ui-monospace/.test(m[1]), '--font-mono must lead with ui-monospace');
});

test('the xterm fontFamily matches the ui-monospace stack', () => {
    const js = readClientJs('terminal-client-factory.js');
    const m = js.match(/fontFamily:\s*'([^']+)'/);
    assert.ok(m, 'fontFamily must be set in the shared xterm options');
    assert.ok(/ui-monospace/.test(m[1]), 'xterm fontFamily must lead with ui-monospace');
    assert.ok(!/fontFamily:/.test(readClientJs('terminal.js')),
        'terminal.js declares its own font again, so there are two stacks');
});

test('no bundled theme overrides --font-mono back to bare SF Mono', () => {
    const themesDir = path.join(__dirname, '..', 'client', 'css', 'themes');
    const offenders = [];
    for (const entry of fs.readdirSync(themesDir)) {
        const file = path.join(themesDir, entry, 'theme.json');
        if (!fs.existsSync(file)) continue;
        const theme = JSON.parse(fs.readFileSync(file, 'utf8'));
        const stack = theme.cssVars && theme.cssVars['--font-mono'];
        if (!stack) continue;
        if (!/ui-monospace/.test(stack)) offenders.push(entry);
    }
    assert.deepEqual(offenders, [],
        `these themes do not include ui-monospace in --font-mono: ${offenders}`);
});

test('the app shell height uses dvh so the iOS toolbar is tracked', () => {
    const css = readClientCss('styles.css');
    assert.ok(/height:\s*100dvh/.test(css), 'body must have a 100dvh height');
    assert.ok(/height:\s*100vh/.test(css), 'body must keep the 100vh fallback');
});


function metricsController(cell, opts = {}, webgl = false) {
    return {
        _webglAddon: webgl ? {} : null,
        term: {
            options: Object.assign(
                { fontSize: 14, lineHeight: 1, fontFamily: 'ui-monospace, Menlo' },
                opts),
            _core: { _renderService: { dimensions: { css: { cell } } } },
        },
    };
}

test('describeCellMetrics reports the numbers that move a row count', () => {
    const { sandbox } = makeSandbox();
    const out = sandbox.TerminalMetrics.describeCellMetrics(
        metricsController({ width: 8.33, height: 14.85 }, {}, true));
    assert.match(out, /font=14/, 'font size must be in the line');
    assert.match(out, /lh=1/, 'line height must be in the line');
    assert.match(out, /cell=8\.33x14\.85/, 'the renderer cell box is the whole point');
    assert.match(out, /renderer=webgl/,
        'the WebGL renderer floors the cell to device pixels and the DOM one '
        + 'does not, so losing the context changes the grid on its own');
    assert.match(out, /family=ui-monospace/);
});

test('describeCellMetrics distinguishes the two cell heights from the incident', () => {
    const { sandbox } = makeSandbox();
    const before = sandbox.TerminalMetrics.describeCellMetrics(
        metricsController({ width: 8.33, height: 14.84 }, {}, true));
    const after = sandbox.TerminalMetrics.describeCellMetrics(
        metricsController({ width: 8.65, height: 16.29 }, {}, false));
    assert.notEqual(before, after,
        'two resizes with different grids must produce different lines, or '
        + 'the log cannot name what moved');
    assert.match(before, /renderer=webgl/);
    assert.match(after, /renderer=dom/);
});

test('describeCellMetrics also reports the boxes, not only the cell', () => {
    const { sandbox } = makeSandbox();
    const out = sandbox.TerminalMetrics.describeCellMetrics(
        metricsController({ width: 8, height: 16 }, {}, true));
    for (const key of ['screen=', 'container=', 'term=']) {
        assert.ok(out.includes(key), `the line must carry ${key}`);
    }
    assert.ok(!out.includes('info='), 'a phantom info= reading would claim a box that no longer exists');
});

test('describeBoxHeights degrades rather than throwing without a DOM', () => {
    const { sandbox } = makeSandbox();
    const out = sandbox.TerminalMetrics.describeBoxHeights();
    assert.ok(typeof out === 'string' && out.length > 0);
    assert.ok(!/undefined/.test(out), 'a log line must never print undefined');
});

test('describeCellMetrics never throws on an unreadable terminal', () => {
    const { sandbox } = makeSandbox();
    const d = sandbox.TerminalMetrics.describeCellMetrics;
    assert.equal(d(null), 'cell=no-term');
    assert.equal(d({}), 'cell=no-term');
    const out = d({ term: { options: { fontSize: 14, lineHeight: 1 } } });
    assert.match(out, /cell=unreadable/);
    assert.match(out, /font=14/, 'a partial read must still report what it could');
});


await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
