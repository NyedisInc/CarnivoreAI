// Same harness style as the other *.node.mjs tests in this directory: no

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');
const src = fs.readFileSync(path.join(CLIENT_JS, 'terminal-input-kind.js'), 'utf8');

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
    const sandbox = { window: {}, console: { warn() {}, log() {} } };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    return sandbox.window.TerminalInputKind;
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
const MOTION_REPORTS = [
    '\x1b[<35;6;3M',
    '\x1b[<35;16;6M',
    '\x1b[<35;26;9M',
];

test('a plain motion report is not user input', () => {
    const api = loadModule();
    for (const report of MOTION_REPORTS) {
        assert.equal(api.isMouseReport(report), true,
            `motion report ${JSON.stringify(report)} must be classified as a mouse report`);
    }
});

test('press, drag and release reports are all mouse reports', () => {
    const api = loadModule();
    assert.equal(api.isMouseReport('\x1b[<0;12;34M'), true);
    assert.equal(api.isMouseReport('\x1b[<32;12;34M'), true);
    assert.equal(api.isMouseReport('\x1b[<0;12;34m'), true);
    assert.equal(api.isMouseReport('\x1b[<64;12;34M'), true);
});

test('the legacy X10 form is recognised too', () => {
    const api = loadModule();
    assert.equal(api.isMouseReport('\x1b[M' + ' '.repeat(3)), true);
    assert.equal(api.isMouseReport('\x1b[MCba'), true);
});

test('real typing is user input and must still re-pin', () => {
    const api = loadModule();
    for (const typed of ['a', 'hello', '\r', '\n', '\t', '\x03', '\x7f', ' ']) {
        assert.equal(api.isMouseReport(typed), false,
            `${JSON.stringify(typed)} is typing, not a mouse report`);
    }
});

test('arrow keys and other CSI sequences are user input', () => {
    const api = loadModule();
    for (const key of ['\x1b[A', '\x1b[B', '\x1b[C', '\x1b[D', '\x1b[Z',
                       '\x1b\r', '\x1b[3~', '\x1b[200~paste\x1b[201~']) {
        assert.equal(api.isMouseReport(key), false,
            `${JSON.stringify(key)} is a key sequence, not a mouse report`);
    }
});

test('a mouse report spliced into typing is treated as user input', () => {
    const api = loadModule();
    assert.equal(api.isMouseReport('x\x1b[<35;6;3M'), false);
    assert.equal(api.isMouseReport('\x1b[<35;6;3Mx'), false);
});

test('malformed and non-string payloads fail open to user input', () => {
    const api = loadModule();
    for (const bad of ['', '\x1b[<', '\x1b[<a;b;cM', '\x1b[<1;2M', '\x1b[M',
                       null, undefined, 42, {}, []]) {
        assert.equal(api.isMouseReport(bad), false,
            `${JSON.stringify(bad)} must fail open to user input`);
    }
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('terminal.js onData guards pinToBottom on the mouse-report check', () => {
    const terminalSrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal.js'), 'utf8');
    const start = terminalSrc.indexOf('this.term.onData(');
    assert.notEqual(start, -1, 'terminal.js must still wire term.onData');
    const body = terminalSrc.slice(start, start + 1600);

    assert.match(body, /TerminalInputKind\s*&&\s*window\.TerminalInputKind\.isMouseReport\(data\)/,
        'onData must classify the payload before acting on it');
    assert.match(body, /TerminalScroll'\)\s*&&\s*!isMouse.*pinToBottom/,
        'pinToBottom must be skipped for mouse reports');
    assert.match(body, /AltScreenScroll'\)\s*&&\s*!isMouse.*noteUserInput/,
        'the altscreen typing quiet-period must not be armed by mouse motion');
    assert.match(body, /this\._sendUserBytes\(new TextEncoder\(\)\.encode\(data\)\)/,
        'mouse reports must still be forwarded to the session');
});

test('currency symbols become Enter, Tab and Shift+Tab on a coarse pointer only (u008-01)', () => {
    const api = loadModule();
    assert.equal(api.softKeyboardShortcut('\u00a5', true), '\n');
    assert.equal(api.softKeyboardShortcut('\u20ac', true), '\t');
    assert.equal(api.softKeyboardShortcut('\u00a3', true), '\x1b[Z');
    for (const sym of ['\u00a5', '\u20ac', '\u00a3', '\uffe1']) {
        assert.equal(api.softKeyboardShortcut(sym, false), sym, 'a desktop keyboard types the symbol: ' + sym);
    }
    assert.equal(api.softKeyboardShortcut('a', true), 'a');
    assert.equal(api.softKeyboardShortcut('\u00a3 5', true), '\u00a3 5', 'only a lone symbol is a shortcut');
    assert.equal(api.isCoarsePointer(), false, 'no matchMedia reads as a fine pointer');
});

test('terminal.js routes onData through the gated shortcut, with no inline remap left (u008-01)', () => {
    const term = fs.readFileSync(path.join(CLIENT_JS, 'terminal.js'), 'utf8');
    assert.match(term, /softKeyboardShortcut\(data\)/);
    assert.doesNotMatch(term, /data = '\\x1b\[Z'/, 'the unconditional remap must stay gone');
});

test('index.html loads terminal-input-kind.js before terminal.js', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    const kind = html.indexOf('terminal-input-kind.js');
    const term = html.indexOf('/static/js/terminal.js');
    assert.notEqual(kind, -1, 'terminal-input-kind.js must be loaded');
    assert.notEqual(term, -1, 'terminal.js must be loaded');
    assert.ok(kind < term,
        'terminal-input-kind.js must load first or onData falls back to re-pinning');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
