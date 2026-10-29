
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(
    path.join(__dirname, '..', 'client', 'js', 'altscreen-scroll.js'),
    'utf8'
);
const keysSrc = fs.readFileSync(
    path.join(__dirname, '..', 'client', 'js', 'altscreen-keys.js'),
    'utf8'
);

let failures = 0;
let passes = 0;
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

const RULE = '─'.repeat(100);

const CLAUDE_LIVE = [
    '',
    ' ▐▛███▜▌   Claude Code v2.1.199',
    '  ‘‘ ’’    ~/Scratch/scratch-lab/altscreen-lab',
    '',
    '❯ TRANSCRIPT LINE 0229 user marker',
    '',
    '⏺ TRANSCRIPT LINE 0230 assistant marker',
    '',
    RULE,
    '❯ Try "how do I log an error?"',
    RULE,
    '  [aaaaaaa] sam@Joe-MBP-M1:⌂/Scratch/scratch-lab/altscreen-lab',
    '  ← for agents',
];

const CLAUDE_TRANSCRIPT = [
    '',
    '❯ TRANSCRIPT LINE 0001 user marker',
    '',
    '⏺ TRANSCRIPT LINE 0002 assistant marker',
    '',
    RULE,
    '  Showing detailed transcript · ctrl+o to toggle · ↑↓ scroll · v to open in code',
    '  shortcuts',
];

const LESS_SCREEN = ['A', 'a', 'aa', 'aal', 'aalii', 'aam', ':'];

const HTOP_SCREEN = [
    '  0[||||    12.5%]   Tasks: 412, 1892 thr; 2 running',
    '  Mem[|||||||  9.7G/16.0G]  Load average: 2.14 1.99 2.03',
    '  PID USER      PRI  NI  VIRT   RES S CPU% MEM%   TIME+  Command',
    'F1Help F2Setup F3Search F4Filter F5Tree F6SortBy F9Kill F10Quit',
];

const CLAUDE_DIALOG = [
    RULE,
    '  Do you want to make this edit to config.json?',
    '  1. Yes   2. Yes, allow all edits   3. No',
    RULE,
];

function fakeTerm(type, rows, baseY = 0) {
    return {
        rows: rows.length,
        buffer: {
            active: {
                type,
                viewportY: baseY,
                baseY,
                getLine(i) {
                    const k = i - baseY;
                    if (k < 0 || k >= rows.length) return null;
                    return { translateToString: () => rows[k] };
                },
            },
        },
    };
}

function load(opts) {
    const withKeys = !opts || opts.withKeys !== false;
    const timers = [];
    const sandbox = {
        window: {},
        console: { warn() {}, log() {} },
        Date,
        setTimeout: (fn, ms) => {
            timers.push({ fn, ms });
            return timers.length;
        },
        clearTimeout: (id) => {
            if (timers[id - 1]) timers[id - 1].cancelled = true;
        },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    if (withKeys) vm.runInContext(keysSrc, sandbox);
    vm.runInContext(src, sandbox);
    const api = sandbox.window.AltScreenScroll;
    const sent = [];
    let term = null;
    api.init(() => term, (d) => sent.push(d));
    return {
        api,
        sent,
        setTerm: (t) => { term = t; },
        tick() {
            const pending = timers.filter((t) => !t.cancelled && !t.done);
            pending.forEach((t) => { t.done = true; t.fn(); });
            return pending.length;
        },
    };
}


test('a buffer with real scrollback is never claimed', () => {
    const m = load();
    m.setTerm(fakeTerm('normal', CLAUDE_LIVE, 900));
    assert.equal(m.api.detectState(fakeTerm('normal', CLAUDE_LIVE, 900)), 'main');
    assert.equal(m.api.scrollByRows(-5), false, 'main screen must fall through to scrollLines');
    assert.deepEqual(m.sent, []);
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE, 1));
    assert.equal(m.api.scrollByRows(-5), false, 'scrollback wins over the buffer label too');
    assert.deepEqual(m.sent, []);
});

test('REGRESSION: a reconnect leaves the NORMAL buffer with no scrollback', () => {
    const m = load();
    assert.equal(m.api.detectState(fakeTerm('normal', CLAUDE_LIVE, 0)), 'live');
    assert.equal(m.api.detectState(fakeTerm('normal', CLAUDE_TRANSCRIPT, 0)), 'transcript');
    m.setTerm(fakeTerm('normal', CLAUDE_TRANSCRIPT, 0));
    m.api.scrollByRows(-4);
    assert.deepEqual(m.sent, ['\x1b[A'.repeat(4)], 'a reconnected client still scrolls');
});

test('claude normal view detected by its prompt frame', () => {
    const m = load();
    assert.equal(m.api.detectState(fakeTerm('alternate', CLAUDE_LIVE)), 'live');
});

test('claude transcript view detected by its own footer', () => {
    const m = load();
    assert.equal(m.api.detectState(fakeTerm('alternate', CLAUDE_TRANSCRIPT)), 'transcript');
});

test('less, htop and a claude dialog are all unknown', () => {
    const m = load();
    assert.equal(m.api.detectState(fakeTerm('alternate', LESS_SCREEN)), 'unknown');
    assert.equal(m.api.detectState(fakeTerm('alternate', HTOP_SCREEN)), 'unknown');
    assert.equal(m.api.detectState(fakeTerm('alternate', CLAUDE_DIALOG)), 'unknown');
});

test('a caret without BOTH rules is not claude', () => {
    const m = load();
    const oneRule = [RULE, '❯ typing', 'plain text'];
    assert.equal(m.api.detectState(fakeTerm('alternate', oneRule)), 'unknown');
    const noCaret = [RULE, '  not a prompt', RULE];
    assert.equal(m.api.detectState(fakeTerm('alternate', noCaret)), 'unknown');
    const shortRule = ['───', '❯ x', '───'];
    assert.equal(m.api.detectState(fakeTerm('alternate', shortRule)), 'unknown');
});

test('an unreadable buffer is unknown, never live', () => {
    const m = load();
    assert.equal(m.api.detectState(null), 'unknown');
    assert.equal(m.api.detectState({ buffer: null }), 'unknown');
});


test('nothing is injected into a non-claude alternate screen', () => {
    for (const screen of [LESS_SCREEN, HTOP_SCREEN, CLAUDE_DIALOG]) {
        const m = load();
        m.setTerm(fakeTerm('alternate', screen));
        assert.equal(m.api.scrollByRows(-5), true, 'gesture is swallowed, not passed on');
        m.tick();
        assert.deepEqual(m.sent, [], 'no bytes may reach a program we cannot identify');
    }
});

test('opening gesture sends ctrl+o alone, arrows only after the view paints', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    assert.equal(m.api.scrollByRows(-5), true);
    assert.deepEqual(m.sent, ['\x0f'], 'arrows in the same write are dropped by claude');
    m.tick();
    assert.deepEqual(m.sent, ['\x0f']);
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.tick();
    assert.equal(m.sent.length, 2);
    assert.equal(m.sent[1], '\x1b[A'.repeat(5), 'five rows up');
});

test('a gesture in the open transcript sends arrows and no toggle', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.scrollByRows(-3);
    assert.deepEqual(m.sent, ['\x1b[A'.repeat(3)]);
    m.api.scrollByRows(7);
    assert.deepEqual(m.sent[1], '\x1b[B'.repeat(7), 'down scrolls down');
    assert.ok(!m.sent.join('').includes('\x0f'), 'no toggle once open');
});

test('N gestures scroll N times the step', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    for (let i = 0; i < 6; i++) m.api.scrollByRows(-4);
    const ups = m.sent.join('').split('\x1b[A').length - 1;
    assert.equal(ups, 24, 'six gestures of four rows is twenty four arrows');
});

test('a gesture is capped so one flick cannot flood the pty', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.scrollByRows(-9999);
    const cap = m.api._timing.MAX_ROWS_PER_GESTURE;
    const bytes = m.sent.join('');
    const pages = bytes.split('\x1b[5~').length - 1;
    const ups = bytes.split('\x1b[A').length - 1;
    assert.equal(pages * 16 + ups, cap, 'capped at exactly MAX_ROWS_PER_GESTURE');
    assert.equal(pages, cap / 16);
});

test('a large move is carried on page keys, not hundreds of arrows', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.scrollByRows(-200);
    const bytes = m.sent.join('');
    const pages = bytes.split('\x1b[5~').length - 1;
    const ups = bytes.split('\x1b[A').length - 1;
    assert.equal(pages * 16 + ups, 200, 'lands on the row that was asked for');
    assert.equal(pages, 12);
    assert.equal(ups, 8);
    assert.equal(pages + ups, 20, '200 rows costs 20 keystrokes, not 200');
});

test('a move smaller than a page is still exact, one arrow per row', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.scrollByRows(-5);
    assert.deepEqual(m.sent, ['\x1b[A'.repeat(5)]);
    assert.ok(!m.sent.join('').includes('\x1b[5~'), 'no partial page');
});

test('the key builder missing sends NOTHING rather than guessing', () => {
    const m = load({ withKeys: false });
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.scrollByRows(-5);
    assert.deepEqual(m.sent, [''], 'a load-order regression scrolls nothing');
});


test('a second gesture in flight does not toggle the view shut', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    m.api.scrollByRows(-5);
    m.api.scrollByRows(-5);
    m.api.scrollByRows(-5);
    const toggles = m.sent.join('').split('\x0f').length - 1;
    assert.equal(toggles, 1, 'exactly one toggle for a burst of gestures');
});

test('exitTranscript closes only when the screen proves the view is open', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    assert.equal(m.api.exitTranscript(), true);
    assert.deepEqual(m.sent, ['\x0f']);
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    assert.equal(m.api.exitTranscript(), false);
    assert.deepEqual(m.sent, ['\x0f'], 'no second toggle');
    m.setTerm(fakeTerm('normal', CLAUDE_LIVE));
    assert.equal(m.api.exitTranscript(), false);
    m.setTerm(fakeTerm('alternate', LESS_SCREEN));
    assert.equal(m.api.exitTranscript(), false, 'never toggle in an unknown program');
    assert.deepEqual(m.sent, ['\x0f']);
});

test('exitTranscript cancels a pending open so its arrows never land', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    m.api.scrollByRows(-5);
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.exitTranscript();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    m.tick();
    assert.deepEqual(m.sent, ['\x0f', '\x0f'], 'no stray arrows into the live prompt');
});


test('nothing is injected while the user is typing', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    m.api.noteUserInput();
    assert.equal(m.api.isTyping(), true);
    assert.equal(m.api.scrollByRows(-5), true, 'gesture swallowed, not forwarded');
    assert.deepEqual(m.sent, []);
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.scrollByRows(-5);
    assert.deepEqual(m.sent, [], 'arrows are held back too');
});

test('the typing guard also gates the delayed arrows', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    m.api.scrollByRows(-5);
    m.setTerm(fakeTerm('alternate', CLAUDE_TRANSCRIPT));
    m.api.noteUserInput();
    m.tick();
    assert.deepEqual(m.sent, ['\x0f'], 'user started typing between toggle and arrows');
});

test('the quiet period is long enough to be a real guard', () => {
    const m = load();
    assert.ok(m.api._timing.TYPING_QUIET_MS >= 1000);
});

test('gaining scrollback mid-open cancels the arrows', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    m.api.scrollByRows(-5);
    m.setTerm(fakeTerm('normal', CLAUDE_LIVE, 500));
    m.tick();
    assert.deepEqual(m.sent, ['\x0f']);
});

test('a zero-row gesture sends nothing', () => {
    const m = load();
    m.setTerm(fakeTerm('alternate', CLAUDE_LIVE));
    assert.equal(m.api.scrollByRows(0), true);
    assert.deepEqual(m.sent, []);
});


test('the wheel and touch paths share one primitive in terminal-scroll.js', () => {
    const ts = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'terminal-scroll.js'), 'utf8'
    );
    assert.ok(ts.includes('function scrollByRows(term, rows)'));
    assert.ok(ts.includes('alt.scrollByRows(rows)'));
    assert.ok(/function handleWheel[\s\S]*?scrollByRows\(term,/.test(ts),
        'wheel must route through scrollByRows');
    assert.ok(/function consumeDragScroll[\s\S]*?scrollByRows\(term, rows\)/.test(ts),
        'touch must route through scrollByRows');
    assert.ok(!ts.includes('canConsumeScroll(term, rows)) {\n            // At the boundary'),
        'the touch path must not re-check the main-screen boundary itself');
});

test('terminal.js wires the module and the typing guard', () => {
    const t = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'terminal.js'), 'utf8'
    );
    assert.ok(t.includes("this._m('AltScreenScroll').init(() => this.term"));
    assert.ok(t.includes("AltScreenScroll').noteUserInput()"));
    assert.ok(t.includes("AltScreenScroll').exitTranscript()"),
        'the d-pad scroll-to-bottom must close the transcript view');
    assert.ok(!t.includes('_applyWheelHandler'),
        'the wheel handler moved to terminal-scroll.js');
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8'
    );
    const iAlt = html.indexOf('altscreen-scroll.js');
    const iTerm = html.indexOf('js/terminal.js');
    assert.ok(iAlt > 0 && iAlt < iTerm, 'must load before terminal.js');
});

await runQueue();
console.log(`${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
