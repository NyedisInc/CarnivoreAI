
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

let failures = 0;
let passes = 0;

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => void} fn  Body; throwing marks the test failed.
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

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('no row surface builds a "needs a keypress" pill any more', () => {
    for (const rel of [
        ['web', 'src', 'lib', 'sidebar-shell', 'row-plan.ts'],
        ['web', 'src', 'lib', 'sidebar-shell', 'SessionRow.svelte'],
    ]) {
        const src = fs.readFileSync(path.join(ROOT, ...rel), 'utf8');
        assert.ok(!/needs a keypress/.test(src),
            `${rel.join('/')} must not carry the removed pill's text`);
    }
    for (const gone of ['session-startup-gate.js', 'session-sidebar-rows.js']) {
        assert.ok(!fs.existsSync(path.join(ROOT, 'client', 'js', gone)),
            `${gone} is retired: the Svelte row is the only row renderer`);
    }
    assert.ok(!fs.existsSync(path.join(
        ROOT, 'client', 'css', 'session-startup-gate.css')),
        'the pill-only stylesheet must be deleted, not just unlinked');
    assert.ok(!fs.existsSync(path.join(
        ROOT, 'web', 'src', 'lib', 'launchpad', 'StartupGateBadge.svelte')),
        'the launchpad pill component must be deleted');
});

test('the sidebar row no longer splices a startup-gate element', () => {
    for (const rel of [
        ['web', 'src', 'lib', 'sidebar-shell', 'row-plan.ts'],
        ['web', 'src', 'lib', 'sidebar-shell', 'SessionRow.svelte'],
    ]) {
        const src = fs.readFileSync(path.join(ROOT, ...rel), 'utf8');
        assert.ok(!/session-startup-gate/.test(src),
            `${rel.join('/')} must not reference the removed pill class`);
    }
});

test('a row with startup_gate set renders no pill while the LED still '
    + 'carries its own label', () => {
    const ledSrc = fs.readFileSync(
        path.join(ROOT, 'client', 'js', 'status-led.js'), 'utf8');
    assert.match(ledSrc, /awaiting_startup_prompt/,
        'the LED must read the raw startup_gate signal on its own');
    assert.match(ledSrc, /waiting-input/,
        'and map it to its own inner state, independent of any pill');
    const labels = fs.readFileSync(
        path.join(ROOT, 'web', 'src', 'lib', 'led.ts'), 'utf8');
    assert.match(labels, /stopped - waiting on you/,
        'the LED tooltip label for the startup gate must still exist and '
        + 'still be load bearing (CLAUDE.md: red and a dropped socket are '
        + 'told apart by the label alone)');
});

test('both merges carry the field off the wire', () => {
    const merges = [
        path.join(ROOT, 'web', 'src', 'lib', 'drawer', 'fetch.ts'),
        path.join(ROOT, 'web', 'src', 'lib', 'sessions', 'running.ts'),
    ];
    for (const file of merges) {
        const src = fs.readFileSync(file, 'utf8');
        assert.match(src, /startup_gate/,
            `${file} builds its rows field by field, so a field it does not `
            + 'copy simply does not exist on the row it hands the renderer');
    }
});

test('the field is read at the WRAPPER level, never inside .session', () => {
    const readers = [
        path.join(ROOT, 'web', 'src', 'lib', 'drawer', 'fetch.ts'),
        path.join(ROOT, 'web', 'src', 'lib', 'sessions', 'running.ts'),
    ];
    for (const file of readers) {
        const src = fs.readFileSync(file, 'utf8');
        assert.ok(!/\.session\.startup_gate/.test(src),
            `${file} must read startup_gate off the SessionInfo wrapper`);
    }
});

test('the retired module and the pill stylesheet are not linked', () => {
    const html = fs.readFileSync(
        path.join(ROOT, 'client', 'index.html'), 'utf8');
    assert.ok(!/session-startup-gate\.(js|css)/.test(html),
        'the startup gate module and the pill-only stylesheet must not be linked');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('answering the prompt repaints the launchpad card', () => {
    const row = fs.readFileSync(path.join(
        ROOT, 'web', 'src', 'lib', 'ledger', 'LedgerSessions.svelte'), 'utf8');
    assert.match(row, /<SessionFace[^>]*\{row\}/,
        'the ledger list must pass the row to the shared face, which is what makes the field a dependency');
    const marks = fs.readFileSync(path.join(ROOT, 'web', 'src', 'lib', 'sessions', 'agent-marks.ts'), 'utf8');
    assert.match(marks, /row\.startup_gate/, 'the shared face must read the field off the row');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
