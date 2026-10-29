
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');

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

function loadModule() {
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const name of ['terminal-prompt-join.js', 'terminal-prompt-ticks.js', 'terminal-prompt-scan.js']) {
        vm.runInContext(fs.readFileSync(path.join(CLIENT_JS, name), 'utf8'),
            sandbox, { filename: name });
    }
    return sandbox.window.TerminalPromptScan;
}

function plain(v) { return JSON.parse(JSON.stringify(v)); }

const CARET = '❯';
const NBSP = ' ';

function makeBuf(rows, opts = {}) {
    const stats = { nullCells: 0, cellArgs: [] };
    const shared = {};
    const specFor = (row) => {
        if (row.cell) {
            return Object.assign({ chars: (row.text || ' ').charAt(0) || ' ' }, row.cell);
        }
        if (row.kind === 'prompt') {
            return { chars: CARET, palette: true, bg: 237, fg: 239 };
        }
        if (row.kind === 'cont') {
            return { chars: (row.text || ' ').charAt(0) || ' ',
                     palette: true, bg: 237, fg: 250 };
        }
        return { chars: (row.text || ' ').charAt(0) || ' ',
                 palette: false, bg: -1, fg: -1 };
    };
    const buf = {
        length: rows.length,
        baseY: opts.baseY === undefined ? 0 : opts.baseY,
        viewportY: opts.viewportY === undefined ? 0 : opts.viewportY,
        type: opts.type || 'normal',
        getNullCell() { stats.nullCells++; return shared; },
        getLine(i) {
            const row = rows[i];
            if (!row) return undefined;
            const spec = specFor(row);
            return {
                isWrapped: !!row.wrapped,
                translateToString(trim) {
                    return trim ? String(row.text).replace(/\s+$/, '') : String(row.text);
                },
                getCell(x, out) {
                    stats.cellArgs.push(out);
                    const target = out || {};
                    target.getChars = () => spec.chars;
                    target.isBgPalette = () => spec.palette;
                    target.getBgColor = () => spec.bg;
                    target.getFgColor = () => spec.fg;
                    return target;
                },
            };
        },
    };
    buf.stats = stats;
    return buf;
}

const promptRow = (text) => ({ kind: 'prompt', text: CARET + NBSP + text });
const indented = (text) => (/^\s/.test(text) ? text : '  ' + text);
const contRow = (text) => ({ kind: 'cont', text: indented(text) });
const wrappedRow = (text) => ({ kind: 'cont', text, wrapped: true });
const plainRow = (text) => ({ kind: 'plain', text });

const Scan = loadModule();

test('a caret over palette 237/239 is a prompt, and its text is the row', () => {
    const buf = makeBuf([plainRow('some output'), promptRow('run the tests')]);
    const got = Scan.scan(buf, { cols: 80 });
    assert.equal(got.length, 1);
    assert.equal(got[0].text, 'run the tests');
    assert.equal(got[0].line, 1);
    assert.equal(got[0].ordinal, 1);
});

test('NEGATIVE CONTROL: an assistant bullet row is never a prompt', () => {
    const buf = makeBuf([plainRow('⏺ Bash(ls -la)'), plainRow('  total 8')]);
    assert.equal(Scan.scan(buf, { cols: 80 }).length, 0);
});

test('NEGATIVE CONTROL: a markdown quote row is never a prompt', () => {
    const buf = makeBuf([plainRow('> quoted text from a document')]);
    assert.equal(Scan.scan(buf, { cols: 80 }).length, 0);
});

const colored = (text, cell) => ({ kind: 'prompt', text: CARET + NBSP + text, cell });
const ruleRow = () => plainRow('─'.repeat(40));

test('COLOUR IS NOT READ: the same prompt in any colour, or none, is found', () => {
    const cells = [
        { palette: true, bg: 237, fg: 239 },
        { palette: true, bg: 237, fg: 246 },
        { palette: true, bg: 237, fg: 250 },
        { palette: false, bg: -1, fg: -1 },
        { palette: true, bg: 17, fg: 153 },
    ];
    for (const cell of cells) {
        const buf = makeBuf([plainRow('output'), colored('run the tests', cell), plainRow('')]);
        const got = plain(Scan.scan(buf, { cols: 80 }));
        assert.deepEqual(got.map(p => p.text), ['run the tests'], JSON.stringify(cell));
    }
});

test('NEGATIVE CONTROL: an indented caret inside tool output is not a prompt', () => {
    const buf = makeBuf([
        plainRow('⏺ Bash(cat notes.txt)'),
        plainRow('  ⎿  ' + CARET + ' not a prompt'),
        plainRow('     ' + CARET + ' nor this, in a code listing'),
        plainRow('  ' + CARET + ' nor this'),
    ]);
    assert.equal(Scan.scan(buf, { cols: 80 }).length, 0);
});

test('NEGATIVE CONTROL: a caret inside an assistant bullet is not a prompt', () => {
    const buf = makeBuf([
        plainRow('⏺ ' + CARET + ' the shell prompt looks like this'),
        plainRow('  ' + CARET + ' and so does this wrapped row'),
    ]);
    assert.equal(Scan.scan(buf, { cols: 80 }).length, 0);
});

test('NEGATIVE CONTROL: a caret with nothing after it, or glued to text, is not a prompt', () => {
    const buf = makeBuf([plainRow(CARET), plainRow(CARET + 'glued'), plainRow(CARET + '   ')]);
    assert.equal(Scan.scan(buf, { cols: 80 }).length, 0);
});

test('NEGATIVE CONTROL: the live input box is excluded anywhere, whatever its colour', () => {
    for (const cell of [{ palette: false, bg: -1, fg: -1 }, { palette: true, bg: 237, fg: 246 }]) {
        const buf = makeBuf([
            plainRow('output'), ruleRow(), colored('typed but never sent', cell), ruleRow(),
            plainRow('output'), promptRow('a real prompt'), plainRow(''), plainRow('reply'),
        ], { baseY: 6 });
        const got = plain(Scan.scan(buf, { cols: 80, baseY: 6, rows: 2 }));
        assert.deepEqual(got.map(p => p.text), ['a real prompt']);
    }
});

test('NEGATIVE CONTROL: a multi-row live input box is excluded by its bottom rule', () => {
    const buf = makeBuf([
        plainRow('output'), ruleRow(), promptRow('first row of a long draft'),
        contRow('second row of it'), ruleRow(),
    ]);
    assert.equal(Scan.scan(buf, { cols: 80 }).length, 0);
});

test('NEGATIVE CONTROL: an option of the numbered choice dialog is not a prompt', () => {
    const withDesc = makeBuf([
        plainRow(''), colored('1. Both: demo now + prod kit', { palette: true, bg: 237, fg: 246 }),
        plainRow('     Run the final pass on the demo stack now.'), plainRow('  2. Hunt root cause'),
    ]);
    assert.equal(Scan.scan(withDesc, { cols: 80 }).length, 0);
    const sibling = makeBuf([
        plainRow('  1. First'), colored('2. Second', { palette: true, bg: 237, fg: 246 }),
        plainRow('  3. Third'),
    ]);
    assert.equal(Scan.scan(sibling, { cols: 80 }).length, 0);
});

test('a prompt that merely starts with a number is still a prompt', () => {
    const buf = makeBuf([promptRow('3. fix the build'), plainRow(''), plainRow('⏺ ok')]);
    assert.deepEqual(plain(Scan.scan(buf, { cols: 80 }).map(p => p.text)), ['3. fix the build']);
});

test('NEGATIVE CONTROL: the reply under a prompt never joins the prompt', () => {
    const buf = makeBuf([
        promptRow('p12 keep 25ms'), plainRow(''), plainRow('  Read 2 files (ctrl+o to expand)'),
        plainRow('⏺ done'),
        promptRow('/effort'), plainRow('  ⎿  Set effort level to max'),
        promptRow('/skills'), plainRow('  - first skill'), plainRow('  - second skill'),
    ]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.deepEqual(got.map(p => p.text), ['p12 keep 25ms', '/effort', '/skills']);
});

test('a prompt that starts with a path still takes its continuation rows', () => {
    const buf = makeBuf([promptRow('/Users/a/notes.md and then'), contRow('some more words')]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.equal(got[0].text, '/Users/a/notes.md and then some more words');
});

test('a blank row ends the prompt (documented cost: later paragraphs are not kept)', () => {
    const buf = makeBuf([promptRow('first paragraph'), plainRow(''), contRow('second paragraph')]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.equal(got.length, 1);
    assert.equal(got[0].text, 'first paragraph');
});

test('a caret over any colour is the head of a prompt cell, and only the caret', () => {
    assert.equal(Scan.isPromptCell({ getChars: () => CARET }), true);
    assert.equal(Scan.isPromptCell({ getChars: () => '>' }), false);
    assert.equal(Scan.isPromptCell(null), false);
    assert.equal(Scan.isPromptHead(CARET + ' x'), true);
    assert.equal(Scan.isPromptHead(CARET + 'x'), false);
});

test('continuation rows fold into the prompt above them', () => {
    const buf = makeBuf([
        promptRow('please run'),
        contRow('the whole suite'),
        plainRow('output follows'),
    ]);
    const got = Scan.scan(buf, { cols: 80 });
    assert.equal(got.length, 1);
    assert.equal(got[0].text, 'please run the whole suite');
});

test('a row cut by the pane width folds with NO space, as copy-output does', () => {
    const buf = makeBuf([
        { kind: 'prompt', text: CARET + NBSP + '/Users/a/lo' },
        wrappedRow('ng/path.txt'),
    ], {});
    const got = Scan.scan(buf, { cols: 11 });
    assert.equal(got[0].text, '/Users/a/long/path.txt');
});

test('a prompt keeps the line breaks the USER typed, beside the folded text', () => {
    const buf = makeBuf([
        promptRow('first line'),
        contRow('second line'),
    ]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.equal(got[0].full, 'first line\nsecond line');
    assert.equal(got[0].text, 'first line second line');
});

test('a row CUT BY THE PANE WIDTH is one line, not two', () => {
    const buf = makeBuf([
        { kind: 'prompt', text: CARET + NBSP + '/Users/a/lo' },
        wrappedRow('ng/path.txt'),
    ], {});
    const got = plain(Scan.scan(buf, { cols: 11 }));
    assert.equal(got[0].full, '/Users/a/long/path.txt');
});

test('a row THE EMULATOR WRAPPED joins on, even ending short of the width', () => {
    const buf = makeBuf([
        promptRow('a frozen hea'),
        wrappedRow('der in excel'),
    ]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.equal(got[0].full, 'a frozen header in excel');
    assert.equal(got[0].text, 'a frozen header in excel');
});

test('NEGATIVE CONTROL: a row the emulator did NOT wrap keeps its break', () => {
    const buf = makeBuf([
        promptRow('first line'),
        contRow('second line'),
        wrappedRow('third line'),
    ]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.equal(got[0].full, 'first line\nsecond linethird line');
});

const PARA_ROWS = [
    '❯ the quick brown fox jumps over the lazy dog near the old sto'
    + 'ne bridge while the river runs slowly beneath it and the eveni'
    + 'ng light fades behind the hills. the quick brown fox    ',
    '  jumps over the lazy dog near the old stone bridge while the '
    + 'river runs slowly beneath it and the evening light fades behin'
    + 'd the hills. the same sentence once more to make the    ',
    '  line good and wide, then reply with only the word bravo     '
    + '                                                              '
    + '                                                        ',
];

const PARA_TYPED =
    'the quick brown fox jumps over the lazy dog near the old stone'
    + ' bridge while the river runs slowly beneath it and the evening'
    + ' light fades behind the hills. the quick brown fox jumps over '
    + 'the lazy dog near the old stone bridge while the river runs sl'
    + 'owly beneath it and the evening light fades behind the hills. '
    + 'the same sentence once more to make the line good and wide, th'
    + 'en reply with only the word bravo';

const CTRL_ROWS = [
    '❯ the first line of the control prompt ends right here        '
    + '                                                              '
    + '                                                        ',
    '  and the second line of the control prompt follows, reply wit'
    + 'h only the word delta                                         '
    + '                                                        ',
];

const CTRL_TYPED =
    'the first line of the control prompt ends right here\nand the s'
    + 'econd line of the control prompt follows, reply with only the '
    + 'word delta';

const LINK_ROWS = [
    '❯ please note this link https://example.com/abcdefghijabcdefgh'
    + 'ijabcdefghijabcdefghijabcdefghijabcdefghijabcdefghijabcdefghij'
    + 'abcdefghijabcdefghijabcdefghijabcdefghijabcdefghijabcde ',
    '  fghijabcdefghijabcdefghijabcdefghijabcdefghijabcdefghij/end '
    + 'and then reply with only the word echo                        '
    + '                                                        ',
];

function reflow(rows, width) {
    const out = [];
    rows.forEach((row, i) => {
        const head = row.slice(0, width);
        const tail = row.slice(width).replace(/\s+$/, '');
        out.push(i === 0 ? { kind: 'prompt', text: head } : contRow(head));
        if (row.length > width) {
            out.push(wrappedRow(tail + ' '.repeat(Math.max(0, width - tail.length))));
        }
    });
    return out;
}

function drawn(rows) {
    return rows.map((row, i) => (i === 0 ? { kind: 'prompt', text: row } : contRow(row)));
}

test('a paragraph the writer wrapped and PADDED is one line, not three', () => {
    const got = plain(Scan.scan(makeBuf(drawn(PARA_ROWS)), { cols: 180 }));
    assert.equal(got[0].full, PARA_TYPED);
    assert.equal(got[0].full.indexOf('\n'), -1);
    assert.equal(got[0].text, PARA_TYPED);
});

test('the same paragraph after the window narrows is still one line', () => {
    const got = plain(Scan.scan(makeBuf(reflow(PARA_ROWS, 174)), { cols: 174 }));
    assert.equal(got[0].full, PARA_TYPED);
    assert.equal(got[0].text, PARA_TYPED);
});

test('NEGATIVE CONTROL: a newline the user typed survives both readings', () => {
    const asDrawn = plain(Scan.scan(makeBuf(drawn(CTRL_ROWS)), { cols: 180 }));
    assert.equal(asDrawn[0].full, CTRL_TYPED);
    assert.equal(asDrawn[0].full.split('\n').length, 2);
    const narrowed = plain(Scan.scan(makeBuf(reflow(CTRL_ROWS, 174)), { cols: 174 }));
    assert.equal(narrowed[0].full, CTRL_TYPED);
    assert.equal(narrowed[0].text.indexOf('\n'), -1);
});

test('a token longer than the pane is never cut into two lines', () => {
    const token = 'https://example.com/' + 'abcdefghij'.repeat(19) + '/end';
    const got = plain(Scan.scan(makeBuf(drawn(LINK_ROWS)), { cols: 180 }));
    assert.equal(got[0].full.indexOf('\n'), -1);
    assert.ok(got[0].full.replace(/ /g, '').includes(token),
        'the token came back broken by something other than one space');
});

test('a one-row prompt is one line with no break in it', () => {
    const buf = makeBuf([promptRow('run the tests')]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.equal(got[0].full, 'run the tests');
});

test('the full text shares the 2000 character budget with the folded text', () => {
    const buf = makeBuf([
        promptRow('x'.repeat(1500)),
        contRow('y'.repeat(1500)),
    ]);
    const got = plain(Scan.scan(buf, { cols: 0 }));
    assert.ok(got[0].full.length <= Scan.MAX_TEXT,
        `full held ${got[0].full.length} characters, over the ${Scan.MAX_TEXT} budget`);
});

test('NEGATIVE CONTROL: the scan no longer ships a lines array', () => {
    const buf = makeBuf([promptRow('first'), contRow('second')]);
    const got = plain(Scan.scan(buf, { cols: 80 }));
    assert.equal(got[0].lines, undefined);
});

test('a prompt in claude bash mode is skipped', () => {
    const buf = makeBuf([promptRow('!ls -la'), promptRow('real prompt')]);
    const got = Scan.scan(buf, { cols: 80 });
    assert.equal(got.length, 1);
    assert.equal(got[0].text, 'real prompt');
});

test('an empty prompt row produces no tick', () => {
    const buf = makeBuf([promptRow(''), promptRow('   ')]);
    assert.equal(Scan.scan(buf, { cols: 80 }).length, 0);
});

test('a repaint that draws the same prompt twice counts once', () => {
    const buf = makeBuf([
        promptRow('deploy it'),
        plainRow(''),
        promptRow('deploy it'),
        plainRow(''),
        promptRow('now revert'),
    ]);
    const got = Scan.scan(buf, { cols: 80 });
    assert.deepEqual(plain(got.map(p => p.text)), ['deploy it', 'now revert']);
    assert.deepEqual(plain(got.map(p => p.ordinal)), [1, 2]);
});

test('the live input box is excluded, and only in the live region', () => {
    const isRule = (row) => /─{20,}/.test(row);
    const rule = '─'.repeat(40);
    const rows = [
        plainRow(rule),
        plainRow('chrome'),
        promptRow('an old prompt'),
        plainRow(''),
        plainRow('output'),
        plainRow(rule),
        promptRow('what I am typing now'),
        plainRow(rule),
    ];
    const buf = makeBuf(rows, { baseY: 5, viewportY: 5 });
    const got = Scan.scan(buf, { cols: 80, baseY: 5, rows: 3, isRule });
    assert.deepEqual(plain(got.map(p => p.text)), ['an old prompt']);
});

test('with no isRule injected the local rule test still excludes the live box', () => {
    const rule = '─'.repeat(40);
    const buf = makeBuf([plainRow(rule), promptRow('typing'), plainRow(rule)], { baseY: 0 });
    assert.equal(Scan.scan(buf, { cols: 80, baseY: 0, rows: 3 }).length, 0);
});

test('the preview is the first 80 characters and the text is capped at 2000', () => {
    const long = 'x'.repeat(3000);
    const buf = makeBuf([promptRow(long)]);
    const got = Scan.scan(buf, { cols: 0 });
    assert.equal(got[0].preview.length, Scan.PREVIEW_CHARS);
    assert.equal(got[0].preview.length, 80);
    assert.equal(got[0].text.length, Scan.MAX_TEXT);
});

test('ONE cell object is allocated for the whole scan and reused every row', () => {
    const rows = [];
    for (let i = 0; i < 50; i++) rows.push(plainRow('line ' + i));
    rows.push(promptRow('a prompt'));
    const buf = makeBuf(rows);
    Scan.scan(buf, { cols: 80 });
    assert.equal(buf.stats.nullCells, 1,
        'getNullCell must be called exactly once per scan');
    assert.ok(buf.stats.cellArgs.length >= 51, 'every row is read');
    const first = buf.stats.cellArgs[0];
    assert.ok(first, 'the shared cell must be passed to getCell');
    for (const arg of buf.stats.cellArgs) {
        assert.equal(arg, first, 'every getCell must receive the SAME cell');
    }
});

test('an unreadable buffer answers with no prompts rather than throwing', () => {
    assert.equal(Scan.scan(null, {}).length, 0);
    assert.equal(Scan.scan({ length: 3, getLine() { throw new Error('x'); } },
        { cols: 80 }).length, 0);
});


test('ticks are proportional to the buffer, not to the prompt index', () => {
    const ticks = Scan.layoutTicks(
        [{ ordinal: 1, line: 0 }, { ordinal: 2, line: 50 }, { ordinal: 3, line: 100 }],
        100, 200);
    assert.deepEqual(plain(ticks.map(t => t.y)), [0, 100, 200]);
    assert.deepEqual(plain(ticks.map(t => t.ordinals)), [[1], [2], [3]]);
});

test('two prompts on adjacent rows are nudged to the minimum gap', () => {
    const ticks = Scan.layoutTicks(
        [{ ordinal: 1, line: 0 }, { ordinal: 2, line: 1 }], 1000, 400);
    assert.equal(ticks[0].y, 0);
    assert.ok(ticks[1].y - ticks[0].y >= Scan.TICK_MIN_GAP,
        `expected at least ${Scan.TICK_MIN_GAP}px between ticks`);
});

test('more prompts than the rail can hold merge into clusters', () => {
    const prompts = [];
    for (let i = 0; i < 40; i++) prompts.push({ ordinal: i + 1, line: i * 10 });
    const ticks = Scan.layoutTicks(prompts, 400, 20);
    assert.equal(ticks.length, 5);
    assert.equal(ticks[0].ordinals.length, 8);
    assert.equal(ticks[0].ordinals[0], 1);
    assert.equal(ticks[4].ordinals[7], 40);
});

test('a rail with no measured height stacks at 0 rather than inventing one', () => {
    const ticks = Scan.layoutTicks(
        [{ ordinal: 1, line: 10 }, { ordinal: 2, line: 900 }], 1000, 0);
    assert.equal(ticks[0].y, 0);
    assert.equal(ticks[1].y, Scan.TICK_MIN_GAP);
});

test('the current ordinal is the last prompt at or above the viewport', () => {
    const prompts = [{ ordinal: 1, line: 5 }, { ordinal: 2, line: 50 },
                     { ordinal: 3, line: 500 }];
    assert.equal(Scan.currentOrdinalFor(prompts, 60), 2);
    assert.equal(Scan.currentOrdinalFor(prompts, 500), 3);
    assert.equal(Scan.currentOrdinalFor(prompts, 0), 1);
    assert.equal(Scan.currentOrdinalFor([], 10), 0);
});

const rowsOf = (lines) => lines.map((text) => ({ text, kind: 'plain' }));
const CODEX_SESSION = [
    '  >_ OpenAI Codex (v0.163.0)', '', '› say only the word pong, then list three colors one per line', '',
    '• pong', '  red', '  blue', '', '  Worked for 2s', '',
    '› and now one more thing', '', '• done', '',
    '› Ask Codex to do anything', '', '  GPT-6-Luna high · ~/work  8 warnings',
];

test('codex: finds the sent prompts by the U+203A marker and drops the live composer', () => {
    const got = plain(Scan.scan(makeBuf(rowsOf(CODEX_SESSION)), { family: 'codex' }));
    assert.deepEqual(got.map((p) => p.text),
        ['say only the word pong, then list three colors one per line', 'and now one more thing']);
    assert.deepEqual(got.map((p) => p.line), [2, 10]);
});

test('codex: NEGATIVE: the same rows scanned as claude find nothing, and a codex scan ignores claude carets', () => {
    assert.equal(Scan.scan(makeBuf(rowsOf(CODEX_SESSION)), {}).length, 0);
    const claudeRows = rowsOf(['❯ run the tests', '', '⏺ ok', '']);
    assert.equal(Scan.scan(makeBuf(claudeRows), { family: 'codex' }).length, 0);
});

test('codex: NEGATIVE: a numbered update menu option is not a prompt', () => {
    const rows = rowsOf(['› 1. Update now (runs `npm install -g @openai/codex`)', '  2. Skip', '  3. Skip until next version']);
    assert.equal(Scan.scan(makeBuf(rows), { family: 'codex' }).length, 0);
});

test('codex: a dialog in place of the composer keeps the last sent prompt', () => {
    const rows = rowsOf(['› edit the file', '', '• I need to write a file.', '', '  Would you like to run this?',
        '  1. Yes', '  2. No']);
    assert.deepEqual(plain(Scan.scan(makeBuf(rows), { family: 'codex' })).map((p) => p.text), ['edit the file']);
});

test('the module stays under the 500-line guideline', () => {
    const lines = fs.readFileSync(
        path.join(CLIENT_JS, 'terminal-prompt-scan.js'), 'utf8').split('\n').length;
    assert.ok(lines < 500,
        `terminal-prompt-scan.js is ${lines} lines, over the 500 limit`);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
