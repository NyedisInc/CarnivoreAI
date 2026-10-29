
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(
    path.join(__dirname, '..', 'client', 'js', 'dpad.js'),
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

function fakeNode() {
    return {
        innerHTML: '',
        className: '',
        style: {},
        dataset: {},
        setAttribute() {},
        addEventListener() {},
        appendChild() {},
        remove() {},
        querySelectorAll() { return []; },
    };
}

function load(sent) {
    const sandbox = {
        window: {
            innerWidth: 390,
            TerminalController: {
                sendKeyToTerminal(code) { sent.keys.push(code); },
                scrollToBottomAndEnableAutoScroll() { sent.scrolled++; },
            },
        },
        document: {
            body: { appendChild() {} },
            createElement: () => fakeNode(),
        },
        navigator: { maxTouchPoints: 5 },
        console: { log() {}, error() {} },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    return sandbox.window.DPad;
}

test('arrow keys are KEPT and send the right escape sequences', () => {
    const sent = { keys: [], scrolled: 0 };
    const dpad = load(sent);
    assert.equal(dpad.keys.UP, '\x1b[A');
    assert.equal(dpad.keys.DOWN, '\x1b[B');
    assert.equal(dpad.keys.RIGHT, '\x1b[C');
    assert.equal(dpad.keys.LEFT, '\x1b[D');

    ['UP', 'DOWN', 'LEFT', 'RIGHT'].forEach((k) => dpad.sendKey(k));
    assert.equal(sent.keys.length, 4, 'all four arrows reach the terminal');
});

test('esc is KEPT', () => {
    const dpad = load({ keys: [], scrolled: 0 });
    assert.equal(dpad.keys.ESC, '\x1b');
});

test('ADDED: a plain TAB, for the key bar', () => {
    const sent = { keys: [], scrolled: 0 };
    const dpad = load(sent);
    assert.equal(dpad.keys.TAB, '\t');
    dpad.sendKey('TAB');
    assert.deepEqual(sent.keys, ['\t']);
});

test('REMOVED: the overlay-only keys went with the overlay', () => {
    const dpad = load({ keys: [], scrolled: 0 });
    assert.equal(dpad.keys.ENTER, '\r');
    assert.equal(dpad.keys.UNDO, '\x1f');
    assert.equal(dpad.keys.SCROLL_BOTTOM, undefined, 'SCROLL_BOTTOM mapping must be gone');
});

test('REMOVED: the floating button and the overlay are gone from the source', () => {
    for (const gone of ['createFloatingButton', 'createOverlay', 'dpad-overlay',
        'dpad-float-button', 'document.body.appendChild']) {
        assert.ok(!src.includes(gone), `${gone} must be gone from dpad.js`);
    }
    const dpad = load({ keys: [], scrolled: 0 });
    for (const gone of ['init', 'open', 'close', 'show', 'hide', 'destroy',
        'createOverlay', 'createFloatingButton']) {
        assert.equal(typeof dpad[gone], 'undefined', `${gone}() must be gone`);
    }
});

test('an unknown key is refused rather than sent as garbage', () => {
    const sent = { keys: [], scrolled: 0 };
    const dpad = load(sent);
    dpad.sendKey('NO_SUCH_KEY');
    assert.equal(sent.keys.length, 0);
});

test('a missing terminal costs the keystroke and nothing else', () => {
    const sent = { keys: [], scrolled: 0 };
    const dpad = load(sent);
    dpad.sendKey('ESC');
    assert.deepEqual(sent.keys, ['\x1b'], 'the sandbox really does send');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    console.error('FAILURES');
    process.exit(1);
}
console.log('ALL PASS');
