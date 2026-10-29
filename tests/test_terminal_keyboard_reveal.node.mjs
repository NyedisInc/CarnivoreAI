
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { TerminalProvider } from '../web/src/lib/terminal-provider/provider.ts';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const SRC = read('client/js/terminal-keyboard-reveal.js');

let failures = 0;
let passes = 0;

/**
 * Run one named assertion, recording the outcome rather than throwing.
 * @param {string} name
 * @param {Function} fn
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

function target() {
    const listeners = {};
    return {
        listeners,
        addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
        removeEventListener(t, fn) {
            listeners[t] = (listeners[t] || []).filter((f) => f !== fn);
        },
        fire(t) { (listeners[t] || []).slice().forEach((fn) => fn({ type: t })); },
    };
}

function realm(opts = {}) {
    const coarse = opts.coarse !== false;
    const calls = [];
    const timers = new Map();
    let nextId = 1;
    const vv = Object.assign(target(), { height: 800 });
    const doc = { activeElement: null };
    const textarea = Object.assign(target(), {
        scrollIntoView(o) { calls.push(['scrollIntoView', o]); },
    });
    const term = {
        textarea,
        _core: { _syncTextArea() { calls.push(['sync']); } },
        scrollToBottom() { calls.push(['termScrollToBottom']); },
    };
    const scroll = { pinToBottom(t) { calls.push(['pin', t === term]); } };
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: doc,
        innerHeight: 800,
        visualViewport: vv,
        matchMedia: (q) => ({ matches: q === '(pointer: coarse)' ? coarse : false }),
        setTimeout: (fn, ms) => { const id = nextId++; timers.set(id, { fn, ms }); return id; },
        clearTimeout: (id) => { timers.delete(id); },
        requestAnimationFrame: () => { throw new Error('a frame never fires in a hidden tab'); },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.TerminalProvider = TerminalProvider;
    vm.createContext(sandbox);
    vm.runInContext(SRC, sandbox, { filename: 'terminal-keyboard-reveal.js' });
    const uninstall = sandbox.TerminalKeyboardReveal.install(term, scroll);
    function flush() {
        const due = [...timers.values()];
        timers.clear();
        due.forEach((t) => t.fn());
        return due;
    }
    return { win: sandbox, doc, vv, term, textarea, calls, timers, flush, uninstall };
}

function tapThenKeyboard(r) {
    r.doc.activeElement = r.textarea;
    r.textarea.fire('focus');
    r.vv.height = 420;
    r.vv.fire('resize');
}

test('THE FIX: focus then a visualViewport resize reveals the input line, no keystroke', () => {
    const r = realm();
    tapThenKeyboard(r);
    assert.deepEqual(r.calls, [], 'nothing runs before the viewport settles');
    assert.equal(r.timers.size, 1, 'the focus and the resize share ONE debounced timer');
    const due = r.flush();
    assert.equal(due[0].ms, r.win.TerminalKeyboardReveal.SETTLE_MS);
    assert.deepEqual(JSON.parse(JSON.stringify(r.calls)), [
        ['pin', true],
        ['sync'],
        ['scrollIntoView', { block: 'center', inline: 'nearest' }],
    ], 'live buffer, textarea on the cursor row, then scrolled into view - in that order');
});

test('THE VIEWPORT PATH: a keyboard that opens AFTER the focus timer is still revealed', () => {
    const r = realm();
    r.doc.activeElement = r.textarea;
    r.textarea.fire('focus');
    r.flush();
    assert.deepEqual(r.calls, [], 'keyboard still down at the focus timer');
    r.vv.height = 420;
    r.vv.fire('resize');
    r.flush();
    assert.deepEqual(r.calls.map((c) => c[0]), ['pin', 'sync', 'scrollIntoView'],
        'the settled resize reveals the input line with no keystroke');
});

test('a resize that keeps arriving re-arms the timer rather than stacking reveals', () => {
    const r = realm();
    tapThenKeyboard(r);
    r.vv.fire('resize');
    r.vv.fire('resize');
    assert.equal(r.timers.size, 1);
    r.flush();
    assert.equal(r.calls.filter((c) => c[0] === 'pin').length, 1);
});

test('no open keyboard, no reveal: a tap alone does not yank the pane to live', () => {
    const r = realm();
    r.doc.activeElement = r.textarea;
    r.textarea.fire('focus');
    r.flush();
    assert.deepEqual(r.calls, [], 'a focus with the keyboard still down changes nothing');
});

test('a desktop (fine pointer) is never touched, even with a shrunken viewport', () => {
    const r = realm({ coarse: false });
    tapThenKeyboard(r);
    r.flush();
    assert.deepEqual(r.calls, []);
});

test('a viewport resize while the terminal is NOT focused does nothing', () => {
    const r = realm();
    r.vv.height = 420;
    r.vv.fire('resize');
    assert.equal(r.timers.size, 0);
    const s = realm();
    tapThenKeyboard(s);
    s.doc.activeElement = null;
    s.flush();
    assert.deepEqual(s.calls, []);
});

test('uninstall removes every listener and the pending timer', () => {
    const r = realm();
    tapThenKeyboard(r);
    r.uninstall();
    assert.equal(r.timers.size, 0);
    assert.equal((r.vv.listeners.resize || []).length, 0);
    assert.equal((r.textarea.listeners.focus || []).length, 0);
    r.vv.fire('resize');
    r.flush();
    assert.deepEqual(r.calls, []);
});

test('NO GEOMETRY CHANGE: the module never refits, resizes or waits on a frame', () => {
    const code = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    assert.ok(code.includes('setTimeout('), 'the scan must read the real code');
    for (const forbidden of ['sendResize', 'requestFit', 'fitAddon', '.fit(',
        'requestAnimationFrame', 'resize(']) {
        assert.ok(!code.includes(forbidden), `must not call ${forbidden}`);
    }
});

test('WIRED AT THE ROOT: terminal.js installs it, index.html loads it first, teardown releases it', () => {
    const html = read('client/index.html');
    const at = html.indexOf('/static/js/terminal-keyboard-reveal.js');
    assert.ok(at > 0, 'index.html must load the module');
    assert.ok(at < html.indexOf('/static/js/terminal.js"'), 'before terminal.js');
    assert.ok(read('client/js/terminal.js').includes(
        "this._uninstallKeyboardReveal = window.TerminalKeyboardReveal.install("));
    assert.ok(read('client/js/terminal-teardown.js').includes('ctl._uninstallKeyboardReveal()'));
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures) {
    console.log('FAILURES');
    process.exit(1);
}
console.log('ALL PASS');
