
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let passes = 0;
let failures = 0;

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

function load(documentPitch) {
    const sandbox = {
        window: {},
        console: { warn() {}, log() {} },
        document: { querySelector: () => ({ clientHeight: documentPitch }) },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(
            path.join(__dirname, '..', 'client', 'js', 'terminal-scroll-step.js'),
            'utf8'
        ),
        sandbox
    );
    return sandbox.window.TerminalScrollStep;
}

function openedTerm(rows, viewportHeight) {
    const viewport = { clientHeight: viewportHeight };
    return {
        rows,
        element: {
            querySelector: (sel) => (sel === '.xterm-viewport' ? viewport : null),
        },
    };
}


test('a second terminal measures its OWN viewport, not the first one', () => {
    const STEP = load(612);

    const second = openedTerm(20, 340);

    assert.equal(STEP.cellHeight(second), 17,
        'cellHeight read the document, not the term it was handed');
});

test('each opened terminal keeps its own pitch in the same document', () => {
    const STEP = load(612);
    const first = openedTerm(34, 612);
    const second = openedTerm(20, 340);

    assert.equal(STEP.cellHeight(first), 18);
    assert.equal(STEP.cellHeight(second), 17);
    assert.notEqual(STEP.cellHeight(first), STEP.cellHeight(second),
        'two terminals of different geometry must not share one pitch');
});

test('rowsForPixels follows the term it was given', () => {
    const STEP = load(612);
    const second = openedTerm(20, 340);
    assert.equal(STEP.rowsForPixels(34, second), 2 * STEP.GESTURE_GAIN);
});


test('a term with no element still uses the document-wide lookup', () => {
    const STEP = load(612);
    assert.equal(STEP.cellHeight({ rows: 34 }), 18);
});



test('the term\'s own element outranks a root argument', () => {
    const STEP = load(612);
    const second = openedTerm(20, 340);
    const wrongRoot = { querySelector: () => ({ clientHeight: 300 }) };
    assert.equal(STEP.cellHeight(second, wrongRoot), 17,
        'an opened term must be measured inside itself, whatever root says');
});

test('a term with no element is measured inside the root it was given', () => {
    const STEP = load(612);
    const root = { querySelector: () => ({ clientHeight: 340 }) };
    assert.equal(STEP.cellHeight({ rows: 20 }, root), 17,
        'root is the rung below the element, and above the document');
    assert.equal(STEP.cellHeight({ rows: 34 }), 18);
});

test('rowsForWheel carries the root down to the pitch', () => {
    const STEP = load(612);
    const root = { querySelector: () => ({ clientHeight: 340 }) };
    const ev = { deltaY: 34, deltaMode: 0 };
    assert.equal(STEP.rowsForWheel(ev, { rows: 20 }, root), 2 * STEP.GESTURE_GAIN);
});

test('an opened term whose viewport is not painted yet falls back', () => {
    const STEP = load(612);
    const notPainted = { rows: 34, element: { querySelector: () => null } };
    assert.equal(STEP.cellHeight(notPainted), STEP.FALLBACK_CELL_HEIGHT);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
