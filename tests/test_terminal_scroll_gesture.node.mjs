
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const cssPath = path.join(__dirname, '..', 'client', 'css', 'styles.css');
const jsPath = path.join(__dirname, '..', 'client', 'js', 'terminal-scroll.js');
const css = fs.readFileSync(cssPath, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const src = fs.readFileSync(jsPath, 'utf8');
const stepSrc = fs.readFileSync(
    path.join(__dirname, '..', 'client', 'js', 'terminal-scroll-step.js'), 'utf8'
);

const GAIN = Number(/GESTURE_GAIN = (\d+)/.exec(stepSrc)[1]);

let failures = 0;
let passes = 0;

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

function ruleBody(sheet, selector) {
    const needle = selector + ' {';
    const at = sheet.indexOf(needle);
    assert.ok(at !== -1, `selector ${selector} not found in stylesheet`);
    const open = at + needle.length;
    const close = sheet.indexOf('}', open);
    assert.ok(close !== -1, `unterminated rule for ${selector}`);
    return sheet.slice(open, close);
}

function loadModule() {
    const listeners = [];
    const sandbox = {
        window: {},
        console: { warn() {}, log() {} },
        Date,
        document: {
            querySelector: () => ({ clientHeight: 612 }),
        },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(stepSrc, sandbox);
    vm.runInContext(src, sandbox);
    const container = {
        addEventListener(type, fn, opts) {
            listeners.push({ type, fn, opts: opts || {} });
        },
    };
    return { api: sandbox.window.TerminalScroll, container, listeners, win: sandbox.window };
}

function touchEvent(opts) {
    const ev = {
        touches: new Array(opts.touches === undefined ? 1 : opts.touches).fill({}),
        cancelable: opts.cancelable === undefined ? true : opts.cancelable,
        defaultPrevented: !!opts.defaultPrevented,
        prevented: false,
    };
    ev.preventDefault = function () {
        ev.prevented = true;
        ev.defaultPrevented = true;
    };
    return ev;
}


test('.terminal-container declares overscroll-behavior', () => {
    const body = ruleBody(css, '.terminal-container');
    assert.match(
        body,
        /overscroll-behavior(-y)?\s*:\s*(contain|none)\s*;/,
        '.terminal-container must contain the pull-to-refresh barrier'
    );
});

test('.terminal-container is still a scroll container', () => {
    const body = ruleBody(css, '.terminal-container');
    assert.match(body, /overflow\s*:\s*hidden\s*;/);
});

test('the barrier is not applied document-wide', () => {
    const bodyRule = ruleBody(css, 'body');
    assert.ok(
        !/overscroll-behavior/.test(bodyRule),
        'body must not carry an unscoped overscroll-behavior'
    );
});


test('cancels a released single-touch drag', () => {
    const { api } = loadModule();
    const ev = touchEvent({});
    api.blockOverscrollEscape(ev);
    assert.equal(ev.prevented, true);
});

test('leaves an already-consumed drag alone', () => {
    const { api } = loadModule();
    const ev = touchEvent({ defaultPrevented: true });
    api.blockOverscrollEscape(ev);
    assert.equal(ev.prevented, false);
});

test('leaves multi-touch alone so pinch-zoom survives', () => {
    const { api } = loadModule();
    const ev = touchEvent({ touches: 2 });
    api.blockOverscrollEscape(ev);
    assert.equal(ev.prevented, false);
});

test('never calls preventDefault on a non-cancelable event', () => {
    const { api } = loadModule();
    const ev = touchEvent({ cancelable: false });
    api.blockOverscrollEscape(ev);
    assert.equal(ev.prevented, false);
});


test('the drag owner is a cancelling CAPTURE listener', () => {
    const { api, container, listeners } = loadModule();
    api.init(container);
    const cancelling = listeners.filter(
        (l) => l.type === 'touchmove' && l.opts.passive === false
    );
    assert.equal(cancelling.length, 2, 'the capture owner plus the bubble backstop');
    assert.equal(cancelling[0].opts.capture, true, 'the owner must capture');
    assert.notEqual(cancelling[1].opts.capture, true, 'the backstop must bubble');
});

test('the auto-scroll race listeners are still passive', () => {
    const { api, container, listeners } = loadModule();
    api.init(container);
    const captureTypes = listeners
        .filter((l) => l.opts.capture === true)
        .map((l) => l.type)
        .sort();
    assert.deepEqual(
        captureTypes,
        ['touchcancel', 'touchend', 'touchmove', 'touchstart', 'wheel']
    );
    const owners = ['touchmove', 'wheel'];
    listeners
        .filter((l) => l.opts.capture === true && owners.indexOf(l.type) === -1)
        .forEach((l) => assert.equal(l.opts.passive, true, `${l.type} must stay passive`));
    listeners
        .filter((l) => l.opts.capture === true && owners.indexOf(l.type) !== -1)
        .forEach((l) => assert.equal(l.opts.passive, false, `${l.type} must cancel`));
});


function fakeTerm(viewportY, baseY) {
    return {
        rows: 34,
        scrolled: [],
        buffer: { active: { viewportY, baseY } },
        scrollLines(n) {
            this.scrolled.push(n);
            this.buffer.active.viewportY = Math.max(
                0, Math.min(baseY, this.buffer.active.viewportY + n)
            );
        },
    };
}

function drive(term, startY, moveY, evOpts) {
    const { api, container, listeners } = loadModule();
    api.init(container, () => term);
    const capture = (type) => listeners
        .filter((l) => l.type === type && l.opts.capture === true)
        .map((l) => l.fn);
    const moveEv = touchEvent(evOpts || {});
    moveEv.touches = [{ pageY: moveY }];

    capture('touchstart').forEach((fn) => fn({ touches: [{ pageY: startY }] }));
    capture('touchmove').forEach((fn) => fn(moveEv));

    api.blockOverscrollEscape(moveEv);
    return { term, ev: moveEv };
}

test('a drag xterm declined still scrolls the terminal', () => {
    const { term, ev } = drive(fakeTerm(1000, 2000), 500, 464);
    assert.deepEqual(term.scrolled, [2 * GAIN], 'must scroll forward by two row-heights');
    assert.equal(ev.prevented, true, 'and still cancel the event');
});

test('drag direction is honoured', () => {
    const { term } = drive(fakeTerm(1000, 2000), 464, 500);
    assert.deepEqual(term.scrolled, [-2 * GAIN], 'finger down scrolls back in history');
});

test('a boundary drag is blocked but not scrolled', () => {
    const { term, ev } = drive(fakeTerm(0, 2000), 464, 500);
    assert.deepEqual(term.scrolled, [], 'nothing to scroll at the top');
    assert.equal(ev.prevented, true, 'pull-to-refresh must still be blocked');
});

test('the other boundary is blocked but not scrolled', () => {
    const { term, ev } = drive(fakeTerm(2000, 2000), 500, 464);
    assert.deepEqual(term.scrolled, []);
    assert.equal(ev.prevented, true);
});

test('a cancel from xterm does not stop the drag from scrolling', () => {
    const { term } = drive(fakeTerm(1000, 2000), 500, 464, { defaultPrevented: true });
    assert.deepEqual(term.scrolled, [2 * GAIN], 'the capture owner scrolls it anyway');
});

test('a selection drag is never stolen by the scroller', () => {
    const { api, container, listeners, win } = loadModule();
    const term = fakeTerm(1000, 2000);
    api.init(container, () => term);
    const fire = (type, y) => listeners
        .filter((l) => l.type === type && l.opts.capture === true)
        .forEach((l) => l.fn({ touches: [{ pageY: y }] }));
    fire('touchstart', 500);
    win.TouchSelect = { isSelecting: () => true };
    fire('touchmove', 464);
    assert.deepEqual(term.scrolled, [], 'selection owns the finger');
    win.TouchSelect = { isSelecting: () => false };
    fire('touchmove', 428);
    assert.deepEqual(term.scrolled, [2 * GAIN], 'and the scroller takes it back after');
});

test('sub-row movement accumulates instead of being discarded', () => {
    const { api, container, listeners } = loadModule();
    const term = fakeTerm(1000, 2000);
    api.init(container, () => term);
    const move = listeners.filter((l) => l.type === 'touchmove' && l.opts.capture === true);
    const start = listeners.filter((l) => l.type === 'touchstart' && l.opts.capture === true);
    start.forEach((l) => l.fn({ touches: [{ pageY: 500 }] }));
    for (let i = 1; i <= 6; i++) {
        move.forEach((l) => l.fn({ touches: [{ pageY: 500 - i * 6 }] }));
        api.blockOverscrollEscape(touchEvent({}));
    }
    assert.equal(
        term.scrolled.reduce((a, b) => a + b, 0), 2 * GAIN,
        '36px of 6px steps must still add up to two row-heights'
    );
});

test('canConsumeScroll is the consumable/escape test, and reads the buffer', () => {
    const { api } = loadModule();
    assert.equal(api.canConsumeScroll(fakeTerm(5, 100), -1), true);
    assert.equal(api.canConsumeScroll(fakeTerm(0, 100), -1), false);
    assert.equal(api.canConsumeScroll(fakeTerm(99, 100), 1), true);
    assert.equal(api.canConsumeScroll(fakeTerm(100, 100), 1), false);
    assert.equal(api.canConsumeScroll(null, 1), false);
    assert.equal(api.canConsumeScroll(fakeTerm(5, 100), 0), false);
});

test('without a term getter it degrades to block-only', () => {
    const { api, container, listeners } = loadModule();
    api.init(container);
    assert.ok(listeners.length > 0);
    const ev = touchEvent({});
    api.blockOverscrollEscape(ev);
    assert.equal(ev.prevented, true);
});

test('multi-touch neither scrolls nor cancels', () => {
    const { api, container, listeners } = loadModule();
    const term = fakeTerm(1000, 2000);
    api.init(container, () => term);
    listeners.filter((l) => l.type === 'touchstart' && l.opts.capture === true)
        .forEach((l) => l.fn({ touches: [{ pageY: 500 }] }));
    listeners.filter((l) => l.type === 'touchmove' && l.opts.capture === true)
        .forEach((l) => l.fn({ touches: [{ pageY: 460 }, { pageY: 400 }] }));
    const ev = touchEvent({ touches: 2 });
    api.blockOverscrollEscape(ev);
    assert.deepEqual(term.scrolled, [], 'pinch-zoom must not scroll the buffer');
    assert.equal(ev.prevented, false);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
