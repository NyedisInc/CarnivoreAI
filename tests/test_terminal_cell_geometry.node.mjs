// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { TerminalProvider } from '../web/src/lib/terminal-provider/provider.ts';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let passes = 0;
let failures = 0;

/**
 * Run one named assertion block immediately, recording the outcome.
 *
 * @param {string} name - what is being asserted.
 * @param {function(): void} fn - the assertions.
 * @returns {void}
 */
function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

const DPR = 3;
const CHAR_WIDTH = 8.65625;
const PARENT_WIDTH = 374;
const SCROLLBAR_WIDTH = 15;

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

function webglDimensions(charWidth, dpr, cols) {
    const deviceCell = Math.floor(charWidth * dpr);
    return {
        cssCellWidth: deviceCell / dpr,
        cssCanvasWidth: Math.round((deviceCell * cols) / dpr),
    };
}

function domDimensions(charWidth, dpr, cols) {
    const deviceCanvas = charWidth * dpr * cols;
    const cssCanvasWidth = Math.round(deviceCanvas / dpr);
    return { cssCellWidth: cssCanvasWidth / cols, cssCanvasWidth };
}

function proposeCols(available, cssCellWidth) {
    return Math.max(2, Math.floor(available / cssCellWidth));
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

function loadMetrics() {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'terminal-metrics.js'), 'utf8');
    const styles = new Map();
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        setTimeout,
        clearTimeout,
        Promise,
        Number,
        Math,
        document: { fonts: null, querySelector: () => null },
        styles,
    };
    sandbox.window = sandbox;
    sandbox.getComputedStyle = (el) => ({
        getPropertyValue: (prop) => String((styles.get(el) || {})[prop] ?? '0px'),
        position: 'relative',
    });
    sandbox.TerminalProvider = TerminalProvider;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    return { metrics: sandbox.TerminalMetrics, sandbox };
}

function makeController(sandbox, model, cols, parentWidth, scrollBarWidth) {
    const parent = { tag: 'parent' };
    const element = { tag: 'xterm', parentElement: parent };
    sandbox.styles.set(parent, { width: `${parentWidth}px` });
    sandbox.styles.set(element, { 'padding-left': '0px', 'padding-right': '0px' });

    const term = {
        cols,
        rows: 34,
        element,
        options: { scrollback: 50000 },
        resize(c, r) { term.cols = c; term.rows = r; },
        _core: {
            viewport: { scrollBarWidth },
            _renderService: {
                get dimensions() {
                    return { css: { cell: { width: model(term.cols).cssCellWidth } } };
                },
            },
        },
    };
    return { term };
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

test('measured device case: webgl pitch is not the font advance', () => {
    const d = webglDimensions(CHAR_WIDTH, DPR, 43);
    assert.equal(d.cssCellWidth, 25 / 3);
    assert.equal(d.cssCanvasWidth, 358);
    assert.ok(Math.abs(CHAR_WIDTH - 8.65625) < 1e-9);
    assert.ok(d.cssCellWidth < CHAR_WIDTH,
        'floored device cell must be narrower than the natural advance');
});

test('measured device case: 43 columns fit the 374px box', () => {
    const available = PARENT_WIDTH - SCROLLBAR_WIDTH;
    const cell = webglDimensions(CHAR_WIDTH, DPR, 43).cssCellWidth;
    assert.equal(proposeCols(available, cell), 43);
    const painted = webglDimensions(CHAR_WIDTH, DPR, 43).cssCanvasWidth;
    assert.equal(painted, 358);
    assert.ok(painted <= PARENT_WIDTH,
        `painted ${painted}px must fit in ${PARENT_WIDTH}px`);
});

test('the invariant holds across every plausible phone width', () => {
    const { metrics, sandbox } = loadMetrics();
    for (let parentWidth = 260; parentWidth <= 1400; parentWidth += 1) {
        for (const dpr of [1, 2, 3]) {
            const model = (cols) => webglDimensions(CHAR_WIDTH, dpr, cols);
            const available = parentWidth - SCROLLBAR_WIDTH;
            const cols = proposeCols(available, model(1).cssCellWidth);
            const ctl = makeController(
                sandbox, model, cols, parentWidth, SCROLLBAR_WIDTH);
            metrics.enforceWidthFit(ctl);
            const painted = model(ctl.term.cols).cssCellWidth * ctl.term.cols;
            assert.ok(painted <= available + metrics.WIDTH_EPSILON_PX,
                `dpr=${dpr} parent=${parentWidth} cols=${ctl.term.cols} `
                + `painted=${painted} available=${available}`);
        }
    }
});

test('dom renderer: the invariant holds after enforcement', () => {
    const { metrics, sandbox } = loadMetrics();
    for (let parentWidth = 260; parentWidth <= 1400; parentWidth += 1) {
        const model = (cols) => domDimensions(CHAR_WIDTH, DPR, cols);
        const available = parentWidth - SCROLLBAR_WIDTH;
        const cols = proposeCols(available, model(80).cssCellWidth);
        const ctl = makeController(
            sandbox, model, cols, parentWidth, SCROLLBAR_WIDTH);
        metrics.enforceWidthFit(ctl);
        const painted = model(ctl.term.cols).cssCellWidth * ctl.term.cols;
        assert.ok(painted <= available + metrics.WIDTH_EPSILON_PX,
            `parent=${parentWidth} cols=${ctl.term.cols} `
            + `painted=${painted} available=${available}`);
    }
});

test('a genuinely oversized grid is shrunk, never shipped', () => {
    const { metrics, sandbox } = loadMetrics();
    const model = () => ({ cssCellWidth: CHAR_WIDTH });
    const ctl = makeController(sandbox, model, 43, PARENT_WIDTH, SCROLLBAR_WIDTH);
    const before = ctl.term.cols * CHAR_WIDTH;
    assert.ok(before > PARENT_WIDTH - SCROLLBAR_WIDTH);
    const result = metrics.enforceWidthFit(ctl);
    assert.equal(result.changed, true);
    assert.equal(result.reason, 'shrunk');
    assert.equal(ctl.term.cols, 41);
    assert.ok(41 * CHAR_WIDTH <= PARENT_WIDTH - SCROLLBAR_WIDTH);
});

test('rows are left alone when columns are dropped', () => {
    const { metrics, sandbox } = loadMetrics();
    const model = () => ({ cssCellWidth: CHAR_WIDTH });
    const ctl = makeController(sandbox, model, 43, PARENT_WIDTH, SCROLLBAR_WIDTH);
    metrics.enforceWidthFit(ctl);
    assert.equal(ctl.term.rows, 34);
});

test('sub-pixel overshoot does not cost a column', () => {
    const { metrics, sandbox } = loadMetrics();
    const available = PARENT_WIDTH - SCROLLBAR_WIDTH;
    const cell = (available + 0.4) / 43;
    const ctl = makeController(
        sandbox, () => ({ cssCellWidth: cell }), 43, PARENT_WIDTH, SCROLLBAR_WIDTH);
    const result = metrics.enforceWidthFit(ctl);
    assert.equal(result.changed, false);
    assert.equal(ctl.term.cols, 43);
});

test('an unmeasurable controller is a no-op, not a resize', () => {
    const { metrics } = loadMetrics();
    assert.equal(metrics.enforceWidthFit(null).reason, 'no-controller');
    assert.equal(metrics.enforceWidthFit({ term: {} }).reason, 'unmeasurable');
});

if (failures > 0) {
    console.error(`\n${failures} failed, ${passes} passed`);
    process.exit(1);
}
console.log(`\nALL PASS (${passes})`);
