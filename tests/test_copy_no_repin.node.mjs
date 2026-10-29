
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientJs = (f) =>
    fs.readFileSync(path.join(__dirname, '..', 'client', 'js', f), 'utf8');

const terminalSrc = clientJs('terminal.js');
const touchSelectSrc = clientJs('touch-select.js');

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


test('scrollOnUserInput is turned OFF at construction', () => {
    assert.ok(/scrollOnUserInput:\s*false/.test(terminalSrc),
        'xterm would otherwise re-pin on its own, from CoreService');
});

test('a real keystroke still takes the user back to live', () => {
    // else.
    const at = terminalSrc.indexOf('this.term.onData(');
    assert.ok(at > -1, 'onData handler not found');
    const body = terminalSrc.slice(at, at + 900);
    assert.ok(body.includes("TerminalScroll').pinToBottom(this.term)"),
        'typing must still pin to bottom');
});

test('the tap-to-bottom listeners are gone, not merely narrowed', () => {
    assert.ok(!/scrollIntoView\(\{\s*behavior: 'smooth', block: 'end'\s*\}\)/
        .test(terminalSrc), 'a tap is not an intent to go to the bottom');
});

test('the pin still has its legitimate owners', () => {
    assert.ok(terminalSrc.includes("this._m('TerminalScroll').pinToBottom(this.term)"));
    assert.ok(terminalSrc.includes('scrollToBottomAndEnableAutoScroll()'));
    assert.ok(terminalSrc.includes('_forceScrollToBottom'));
});


function loadTouchSelect(rect, rows) {
    const listeners = [];
    const screenEl = {
        getBoundingClientRect: () => ({
            ...rect,
            width: rect.right - rect.left,
            height: rect.bottom - rect.top,
        }),
        dispatchEvent: () => true,
    };
    const element = {
        querySelector: () => screenEl,
        parentElement: { addEventListener: (t, f, o) => listeners.push([t, f, o]) },
    };
    const sandbox = {
        window: { matchMedia: () => ({ matches: true }) },
        console: { warn() {}, log() {} },
        document: { addEventListener() {}, activeElement: null },
        setTimeout: () => 0,
        clearTimeout: () => {},
        MouseEvent: class {},
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(touchSelectSrc, sandbox);
    sandbox.window.TouchSelect.init({
        term: { element, rows, textarea: null, hasSelection: () => false },
        _showStatusPill() {},
    });
    return sandbox.window.TouchSelect;
}

const RECT = { left: 0, top: 100, right: 390, bottom: 712 };
const ROWS = 34;

test('a touch below the last row is pulled back inside the row band', () => {
    const ts = loadTouchSelect(RECT, ROWS);
    const at = ts.clampToRows(200, 760);
    assert.ok(at.y < RECT.bottom, 'must not sit past the last row');
    assert.ok(at.y <= RECT.bottom - 18, 'must clear the edge row entirely');
    assert.ok(at.y > RECT.top, 'and must not overshoot to the top');
});

test('a touch above the first row is clamped too', () => {
    const ts = loadTouchSelect(RECT, ROWS);
    const at = ts.clampToRows(200, 0);
    assert.ok(at.y >= RECT.top + 18, 'upward auto-scroll is the same defect');
});

test('a touch already inside the rows is left exactly alone', () => {
    const ts = loadTouchSelect(RECT, ROWS);
    const at = ts.clampToRows(200, 400);
    assert.equal(at.x, 200, 'clamping must not move a selection the user aimed');
    assert.equal(at.y, 400, 'clamping must not move a selection the user aimed');
});

test('horizontal clamping keeps the pointer on the screen element', () => {
    const ts = loadTouchSelect(RECT, ROWS);
    assert.ok(ts.clampToRows(-50, 400).x >= RECT.left);
    assert.ok(ts.clampToRows(9999, 400).x <= RECT.right);
});

test('an unmeasurable box declines to clamp rather than guessing', () => {
    const ts = loadTouchSelect({ left: 0, top: 0, right: 0, bottom: 0 }, ROWS);
    const at = ts.clampToRows(200, 760);
    assert.equal(at.x, 200);
    assert.equal(at.y, 760);
});

test('every synthetic mouse event goes through the clamp', () => {
    const at = touchSelectSrc.indexOf('function dispatchMouse(');
    assert.ok(at > -1);
    const body = touchSelectSrc.slice(at, touchSelectSrc.indexOf('}', at + 400));
    assert.ok(body.includes('clampToRows(x, y)'));
    assert.ok(body.includes('clientX: at.x'));
    assert.ok(body.includes('clientY: at.y'));
    assert.ok(!/clientX: x,/.test(body), 'raw coordinates must not survive');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
