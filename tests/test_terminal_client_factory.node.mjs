// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');

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

function recordingContainer(viewportHeight) {
    const viewport = { clientHeight: viewportHeight, scrollTop: 0, scrollHeight: 0 };
    return {
        listeners: [],
        addEventListener(type, fn, opts) {
            this.listeners.push({ type, fn, opts: opts || {} });
        },
        querySelector: (sel) => (sel === '.xterm-viewport' ? viewport : null),
    };
}

function load(files) {
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        document: { querySelector: () => null, getElementById: () => null },
        Date, JSON, Math, Object, Promise, Array, String, Number,
        setTimeout, clearTimeout, setInterval, clearInterval,
        TextEncoder,
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    for (const f of files) {
        vm.runInContext(fs.readFileSync(path.join(CLIENT_JS, f), 'utf8'),
            sandbox, { filename: f });
    }
    return sandbox.window;
}


test('two scroll owners wire their OWN container, and the second is not refused', () => {
    const win = load(['terminal-scroll-step.js', 'terminal-scroll.js']);

    const first = win.TerminalScroll.create();
    const second = win.TerminalScroll.create();
    assert.notEqual(first, second, 'create() must not hand back one object');

    const boxA = recordingContainer(612);
    const boxB = recordingContainer(340);
    first.init(boxA, () => ({ rows: 34 }));
    second.init(boxB, () => ({ rows: 20 }));

    assert.ok(boxA.listeners.length > 0, 'the first container got no listeners');
    assert.equal(boxB.listeners.length, boxA.listeners.length,
        'the second terminal was refused its gesture listeners');

    for (const [name, box] of [['first', boxA], ['second', boxB]]) {
        const wheel = box.listeners.find((l) => l.type === 'wheel');
        assert.ok(wheel, `the ${name} container has no wheel listener`);
        assert.equal(wheel.opts.capture, true,
            `the ${name} wheel listener must run before xterm's`);
        assert.equal(wheel.opts.passive, false,
            `the ${name} wheel listener must be able to cancel`);
    }
});

test('two scroll owners keep INDEPENDENT gesture latches', () => {
    const win = load(['terminal-scroll-step.js', 'terminal-scroll.js']);
    const first = win.TerminalScroll.create();
    const second = win.TerminalScroll.create();

    // nothing at all
    first.noteUserScroll();
    assert.equal(first.isGestureActive(), true);
    assert.equal(second.isGestureActive(), false,
        'a gesture in one terminal must not latch the other');

    const atBottom = { buffer: { active: { viewportY: 10, baseY: 10 } } };
    assert.equal(first.shouldFollowOutput(atBottom), false);
    assert.equal(second.shouldFollowOutput(atBottom), true,
        'the second terminal must keep following its own output');
});

test('two input buffers keep INDEPENDENT connection generations', () => {
    const win = load(['terminal-input-buffer.js']);
    const first = win.TerminalInputBuffer.create();
    const second = win.TerminalInputBuffer.create();

    const genA = first.arm('terminal one');
    const genB = second.arm('terminal two');

    assert.equal(first.offer(genA, new Uint8Array([0x61])), 'buffered');
    assert.equal(first.heldByteCount(), 1);

    assert.equal(first.offer(genA, new Uint8Array([0x62])), 'buffered',
        'the second terminal arming must not supersede the first');
    assert.equal(first.heldByteCount(), 2);

    assert.equal(second.heldByteCount(), 0);
    assert.equal(second.offer(genB, new Uint8Array([0x63])), 'buffered');
    assert.equal(second.heldByteCount(), 1);

    const r = first.release(genA);
    assert.equal(r.outcome, 'flushed');
    assert.equal(r.bytes, 2);
    assert.equal(second.heldByteCount(), 1, 'the other batch must be untouched');
    assert.equal(second.state(), 'buffering');
});

test('an overflow poisons ONE generation, not both terminals', () => {
    const win = load(['terminal-input-buffer.js']);
    const first = win.TerminalInputBuffer.create();
    const second = win.TerminalInputBuffer.create();
    const genA = first.arm('one');
    const genB = second.arm('two');

    const over = new Uint8Array(first.MAX_BUFFERED_BYTES + 1);
    assert.equal(first.offer(genA, over), 'rejected_overflow');
    assert.equal(first.offer(genA, new Uint8Array([1])), 'refused_overflowed');

    assert.equal(second.state(), 'buffering');
    assert.equal(second.offer(genB, new Uint8Array([1])), 'buffered');
});

test('the other four modules hand back independent instances too', () => {
    const win = load([
        'terminal-layout.js',
        'terminal-startup-notice.js',
    ]);
    for (const name of ['TerminalLayout', 'TerminalStartupNotice']) {
        assert.equal(typeof win[name].create, 'function',
            `${name} has no create()`);
        assert.notEqual(win[name].create(), win[name].create(),
            `${name}.create() hands back one shared object`);
    }

    const a = win.TerminalStartupNotice.create();
    const b = win.TerminalStartupNotice.create();
    a.show('ses_a', 'failed');
    b.show('ses_b', 'none');
    assert.equal(a.sessionId(), 'ses_a');
    assert.equal(b.sessionId(), 'ses_b',
        'two notices must not share the session they reflect');
});


test('the module-level exports drive ONE default instance', () => {
    const win = load(['terminal-scroll-step.js', 'terminal-scroll.js']);

    win.TerminalScroll.noteUserScroll();
    assert.equal(win.TerminalScroll.isGestureActive(), true,
        'the module exports must share one instance');

    const fresh = win.TerminalScroll.create();
    assert.equal(fresh.isGestureActive(), false,
        'create() must not inherit the default instance state');
});

test('the default TerminalScroll still wires a container through init()', () => {
    const win = load(['terminal-scroll-step.js', 'terminal-scroll.js']);
    const box = recordingContainer(612);
    win.TerminalScroll.init(box, () => ({ rows: 34 }));
    assert.ok(box.listeners.some((l) => l.type === 'wheel'),
        'the legacy init() path stopped wiring the wheel');
    assert.ok(box.listeners.some((l) => l.type === 'touchmove'),
        'the legacy init() path stopped wiring the drag');
});

test('the default TerminalInputBuffer still holds and releases', () => {
    const win = load(['terminal-input-buffer.js']);
    const gen = win.TerminalInputBuffer.arm('the live client');
    assert.equal(win.TerminalInputBuffer.offer(gen, new Uint8Array([7])), 'buffered');
    assert.equal(win.TerminalInputBuffer.heldByteCount(), 1);
    assert.equal(win.TerminalInputBuffer.release(gen).outcome, 'flushed');
    assert.equal(win.TerminalInputBuffer.state(), 'ready');
});

test('every converted module publishes create() ALONGSIDE its legacy surface', () => {
    const cases = [
        ['terminal-scroll.js', 'TerminalScroll',
            ['init', 'shouldFollowOutput', 'pinToBottom', 'handleWheel'],
            ['terminal-scroll-step.js']],
        ['terminal-layout.js', 'TerminalLayout',
            ['install', 'requestFit', 'requestFitAfterTransition'], []],
        ['terminal-input-buffer.js', 'TerminalInputBuffer',
            ['arm', 'offer', 'release', 'discard', 'begin', 'send',
                'flushOnReady', 'abandon', 'armReadyBackstop'], []],
        ['altscreen-scroll.js', 'AltScreenScroll',
            ['init', 'scrollByRows', 'exitTranscript', 'noteUserInput'], []],
        ['terminal-startup-notice.js', 'TerminalStartupNotice',
            ['show', 'clear', 'sessionId'], []],
    ];
    for (const [file, name, methods, before] of cases) {
        const win = load([...before, file]);
        assert.equal(typeof win[name].create, 'function',
            `${name} publishes no create()`);
        for (const m of methods) {
            assert.equal(typeof win[name][m], 'function',
                `${name}.${m} is gone from the legacy surface`);
        }
    }
});


test('the factory refuses to build before terminal.js registers the class', () => {
    const win = load(['terminal-client-factory.js']);
    assert.equal(typeof win.CloudeTerminal.createTerminalClient, 'function');
    assert.throws(() => win.CloudeTerminal.createTerminalClient(null),
        /no terminal class registered/);
});

test('the factory builds the registered class and passes what it was given', () => {
    const win = load(['terminal-client-factory.js']);
    const built = [];
    function FakeTerminal(options) { built.push(options); }
    win.CloudeTerminal.register(FakeTerminal);

    const host = recordingContainer(612);
    const client = win.CloudeTerminal.createTerminalClient(host, {
        wiring: { TerminalScroll: 'mine' },
        sessionId: 'ses_a',
        role: { writable: true },
    });
    assert.ok(client instanceof FakeTerminal);
    assert.equal(built.length, 1);
    assert.equal(built[0].container, host, 'the container must be passed through');
    assert.equal(built[0].wiring.TerminalScroll, 'mine');
    assert.equal(built[0].sessionId, 'ses_a');
    assert.deepEqual(built[0].role, { writable: true });
    assert.equal(typeof built[0].chrome.statusText, 'function');
});

test('the chrome record RESOLVES ON EACH CALL, it does not capture', () => {
    const win = load(['terminal-client-factory.js']);
    const doc = { byId: {}, getElementById(id) { return this.byId[id] || null; } };
    const chrome = win.CloudeTerminal.readPageChrome(doc);
    assert.equal(chrome.statusText(), null);
    doc.byId.statusText = { id: 'statusText' };
    assert.equal(chrome.statusText().id, 'statusText');
});

test('the boot line builds the ONE live instance through the factory', () => {
    const src = fs.readFileSync(path.join(CLIENT_JS, 'terminal.js'), 'utf8');
    assert.ok(src.includes('window.CloudeTerminal.register(Terminal);'),
        'terminal.js must hand its class to the factory');
    assert.ok(src.includes('window.CloudeTerminal.createTerminalClient('),
        'the boot line must go through the factory');
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '')
        .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
    const constructions = (code.match(/new Terminal\(/g) || []).length;
    assert.equal(constructions, 0,
        `terminal.js constructs a Terminal directly in ${constructions} place(s)`);

    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    const order = [...html.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)]
        .map((m) => m[1]);
    const factory = order.indexOf('terminal-client-factory.js');
    assert.ok(factory >= 0, 'the factory must be in index.html or it is dead code');
    assert.ok(factory < order.indexOf('terminal.js'),
        'the factory must load BEFORE terminal.js, which calls it');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
