
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

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

function loadResolver() {
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const context = { window: fakeWindow, console: { warn() {}, error() {} } };
    vm.createContext(context);
    vm.runInContext(
        fs.readFileSync(path.join(ROOT, 'client', 'js', 'session-label.js'), 'utf8'),
        context,
        { filename: 'session-label.js' }
    );
    return context.window.SessionLabel;
}

const SL = loadResolver();

test('a label wins over the tmux name', () => {
    assert.equal(
        SL.resolve({ name: 'cloude_Media', label: 'Image Tool' }),
        'Image Tool'
    );
});

test('no label falls back to the cloude_-stripped tmux name', () => {
    assert.equal(SL.resolve({ name: 'cloude_Media', label: null }), 'Media');
});

test('an external name with no cloude_ prefix is rendered verbatim', () => {
    assert.equal(SL.resolve({ name: 'someones-shell' }), 'someones-shell');
});

test('an EMPTY label counts as no label, never as a blank name', () => {
    assert.equal(SL.resolve({ name: 'cloude_Media', label: '' }), 'Media');
    assert.equal(SL.resolve({ name: 'cloude_Media', label: '   ' }), 'Media');
});

test('a non-string label is ignored rather than stringified', () => {
    for (const bad of [null, undefined, 0, 42, {}, [], true]) {
        assert.equal(SL.resolve({ name: 'cloude_Media', label: bad }), 'Media');
    }
});

test('neither a label nor a name resolves to null, not to a blank', () => {
    assert.equal(SL.resolve({}), null);
    assert.equal(SL.resolve({ name: '', label: '' }), null);
    assert.equal(SL.resolve(null), null);
    assert.equal(SL.resolve(undefined), null);
});

test('a tmux name that is ONLY the prefix resolves to null, not to ""', () => {
    assert.equal(SL.resolve({ name: 'cloude_' }), null);
});

test('a label keeps every character a human typed', () => {
    for (const label of [
        'Image Tool',
        'client: acme',
        'v2.1.3 rollout',
        'say "hello"',
        '$RATE limits',
        'a/b/c',
        "it's fine",
        '<b>not html</b>',
    ]) {
        assert.equal(SL.resolve({ name: 'cloude_x', label }), label);
    }
});

test('a label is NOT trimmed away, only its surrounding whitespace', () => {
    assert.equal(SL.resolve({ name: 'cloude_x', label: '  spaced  ' }), 'spaced');
    assert.equal(SL.resolve({ name: 'cloude_x', label: 'two  inner' }), 'two  inner');
});

test('the toast field names resolve through the same one rule', () => {
    assert.equal(
        SL.resolveToast({ session_label: 'Image Tool', session_name: 'cloude_Media' }),
        'Image Tool'
    );
    assert.equal(
        SL.resolveToast({ session_label: null, session_name: 'cloude_Media' }),
        'Media'
    );
    assert.equal(SL.resolveToast({ session_label: null, session_name: null }), null);
    assert.equal(SL.resolveToast(null), null);
});

test('stripPrefix:false changes the SPELLING of the fallback, not the rule', () => {
    assert.equal(
        SL.resolve({ name: 'cloude_Media' }, { stripPrefix: false }),
        'cloude_Media'
    );
    assert.equal(
        SL.resolve({ name: 'cloude_Media', label: 'Image Tool' },
                   { stripPrefix: false }),
        'Image Tool'
    );
    assert.equal(SL.resolve({}, { stripPrefix: false }), null);
    assert.equal(SL.resolve({ name: '  ' }, { stripPrefix: false }), null);
    assert.equal(SL.resolve({ name: 'cloude_Media' }, {}), 'Media');
    assert.equal(SL.resolve({ name: 'cloude_Media' }, null), 'Media');
});

test('UNKNOWN is a sentence a user can read, not an empty string', () => {
    assert.equal(typeof SL.UNKNOWN, 'string');
    assert.ok(SL.UNKNOWN.trim().length > 0);
});

if (failures > 0) {
    console.error(`\n${failures} failed, ${passes} passed`);
    process.exit(1);
}
console.log(`\n${passes} passed`);
