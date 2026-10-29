// Same harness style as the other *.node.mjs tests in this directory:

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(
    path.join(__dirname, '..', 'client', 'js', 'terminal-scroll.js'),
    'utf8'
);

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

/** Fresh module instance with a bare window/console. */
function loadModule() {
    const listeners = [];
    const sandbox = {
        window: {},
        console: { warn() {}, log() {} },
        Date,
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    return { api: sandbox.window.TerminalScroll, listeners };
}

function fakeTerm(viewportY, baseY) {
    return { buffer: { active: { viewportY, baseY } } };
}

function fakeContainer(sink) {
    return {
        addEventListener(type, handler) {
            sink[type] = handler;
        },
    };
}

test('at the bottom counts as pinned', () => {
    const { api } = loadModule();
    assert.equal(api.isPinnedToBottom(fakeTerm(500, 500)), true);
});

test('scrolled up is not pinned', () => {
    const { api } = loadModule();
    assert.equal(api.isPinnedToBottom(fakeTerm(120, 500)), false);
});

test('an unreadable buffer fails safe to pinned (keep following output)', () => {
    const { api } = loadModule();
    assert.equal(api.isPinnedToBottom({}), true);
    assert.equal(api.isPinnedToBottom(null), true);
});

test('output is followed while the user sits at the bottom', () => {
    const { api } = loadModule();
    assert.equal(api.shouldFollowOutput(fakeTerm(500, 500)), true);
});

test('REGRESSION: output does not chase a viewport the user scrolled up', () => {
    const { api } = loadModule();
    assert.equal(api.shouldFollowOutput(fakeTerm(10, 500)), false);
});

test('REGRESSION: a gesture suppresses follow even while at the bottom', () => {
    const { api } = loadModule();
    api.noteUserScroll();
    assert.equal(api.isGestureActive(), true);
    assert.equal(api.shouldFollowOutput(fakeTerm(500, 500)), false);
});

test('touchstart marks a gesture, so a write during a drag cannot yank', () => {
    const { api } = loadModule();
    const sink = {};
    api.init(fakeContainer(sink));
    assert.equal(typeof sink.touchstart, 'function', 'touchstart wired');
    assert.equal(typeof sink.touchmove, 'function', 'touchmove wired');
    assert.equal(typeof sink.wheel, 'function', 'wheel wired');

    sink.touchstart();
    assert.equal(api.shouldFollowOutput(fakeTerm(10, 500)), false);
    assert.equal(api.shouldFollowOutput(fakeTerm(500, 500)), false);
});

test('touch observers stay passive; the drag owner cancels', () => {
    const registered = [];
    const sandbox = {
        window: {},
        console: { warn() {}, log() {} },
        Date,
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    sandbox.window.TerminalScroll.init({
        addEventListener(type, handler, options) {
            registered.push({ type, options: options || {} });
        },
    });
    const observers = registered.filter((r) => r.options.capture === true);
    ['touchstart', 'touchend'].forEach((type) => {
        const found = observers.filter((r) => r.type === type);
        assert.equal(found.length, 1, `exactly one capture-phase ${type} observer`);
        assert.equal(found[0].options.passive, true, `${type} must be passive`);
    });
    ['touchmove', 'wheel'].forEach((type) => {
        const owners = observers.filter((r) => r.type === type);
        assert.equal(owners.length, 1, `exactly one capture-phase ${type} owner`);
        assert.equal(owners[0].options.passive, false, `${type} must be able to cancel`);
    });
});

test('pinToBottom clears the latch and scrolls', () => {
    const { api } = loadModule();
    let scrolled = 0;
    const term = fakeTerm(10, 500);
    term.scrollToBottom = () => { scrolled++; };

    api.noteUserScroll();
    assert.equal(api.isGestureActive(), true);

    api.pinToBottom(term);
    assert.equal(scrolled, 1, 'scrollToBottom called');
    assert.equal(api.isGestureActive(), false, 'latch cleared');
});

test('pinToBottom survives a terminal whose scrollToBottom throws', () => {
    const { api } = loadModule();
    const term = fakeTerm(10, 500);
    term.scrollToBottom = () => { throw new Error('disposed'); };
    api.pinToBottom(term);  // must not propagate
    assert.equal(api.isGestureActive(), false);
});

test('init is idempotent across session swaps', () => {
    const { api } = loadModule();
    let count = 0;
    const container = { addEventListener() { count++; } };
    api.init(container);
    const first = count;
    api.init(container);
    assert.equal(count, first, 'second init must not double-wire');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    console.error('FAILURES');
    process.exit(1);
}
console.log('ALL PASS');
