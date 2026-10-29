
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

let passes = 0;
let failures = 0;

async function test(name, fn) {
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


function loadWriter() {
    const sandbox = { window: {}, console: { log() {}, error() {} } };
    sandbox.window.window = sandbox.window;
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(path.join(ROOT, 'client', 'js', 'theme-var-writer.js'), 'utf8'),
        sandbox, { filename: 'theme-var-writer.js' });
    return sandbox.window.ThemeVarWriter;
}

function styleSpy() {
    const values = new Map();
    const setCalls = [];
    const removeCalls = [];
    return {
        values, setCalls, removeCalls,
        setProperty(name, value) { setCalls.push(name); values.set(name, value); },
        removeProperty(name) { removeCalls.push(name); values.delete(name); },
    };
}

await test('writer: an unchanged value is never re-set', () => {
    const w = loadWriter();
    const style = styleSpy();
    const a = w.applyVarDiff(style, {}, { '--bg': '#111' });
    assert.deepEqual(style.setCalls, ['--bg']);
    const b = w.applyVarDiff(style, a.values, { '--bg': '#111' });
    assert.deepEqual(style.setCalls, ['--bg'], 'a second identical value must not call setProperty again');
    assert.equal(b.skipped, 1);
});

await test('writer: a CHANGED value still gets set - the skip is per-value, not per-name', () => {
    const w = loadWriter();
    const style = styleSpy();
    const a = w.applyVarDiff(style, {}, { '--bg': '#111' });
    w.applyVarDiff(style, a.values, { '--bg': '#222' });
    assert.deepEqual(style.setCalls, ['--bg', '--bg']);
    assert.equal(style.values.get('--bg'), '#222');
});

await test('writer: a dropped name is removed UNCONDITIONALLY, never skipped', () => {
    const w = loadWriter();
    const style = styleSpy();
    const a = w.applyVarDiff(style, {}, { '--bg': '#111', '--fg': '#eee' });
    w.applyVarDiff(style, a.values, { '--bg': '#111' });
    assert.deepEqual(style.removeCalls, ['--fg']);
    assert.equal(style.values.has('--fg'), false);
});

await test('writer: a value unchanged in TEXT but re-typed is still treated as unchanged (string compare)', () => {
    const w = loadWriter();
    const style = styleSpy();
    const a = w.applyVarDiff(style, {}, { '--n': 5 });
    style.setCalls.length = 0;
    w.applyVarDiff(style, a.values, { '--n': 5 });
    assert.deepEqual(style.setCalls, [], 'the same value re-supplied must still be a skip');
});


function loadRegistry(store) {
    const style = styleSpy();
    const backing = { ...store };
    const documentElement = { style, dataset: {} };
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: {
            documentElement,
            createElement: () => ({ style: {}, setAttribute() {}, appendChild() {} }),
            head: { appendChild() {} },
            addEventListener() {}, removeEventListener() {},
            getElementById: () => null, querySelector: () => null,
            querySelectorAll: () => [],
        },
        localStorage: {
            getItem: (k) => (k in backing ? backing[k] : null),
            setItem: (k, v) => { backing[k] = String(v); },
            removeItem: (k) => { delete backing[k]; },
        },
        setTimeout, clearTimeout, setInterval: () => 0, clearInterval,
        fetch: () => Promise.reject(new Error('no network pre-auth')),
        Set, Map, JSON, Object, Array, Promise, Error,
        location: { href: '' }, navigator: { userAgent: '' },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(path.join(ROOT, 'client', 'js', 'theme-var-writer.js'), 'utf8'),
        sandbox, { filename: 'theme-var-writer.js' });
    vm.runInContext(
        fs.readFileSync(path.join(ROOT, 'client', 'js', 'themes', 'registry.js'), 'utf8'),
        sandbox, { filename: 'registry.js' });
    return { sandbox, style, backing };
}

function manifest(id) {
    return JSON.parse(fs.readFileSync(
        path.join(ROOT, 'client', 'css', 'themes', id, 'theme.json'), 'utf8'));
}
const MATRIX = manifest('matrix');
const CLAUDE = manifest('claude');
const VARS_CACHE_KEY = 'carnivore.theme.vars';
const THEME_KEY = 'carnivore.theme';

await test('registry: re-applying the SAME cached theme costs zero setProperty calls the second time', () => {
    const { sandbox, style } = loadRegistry({
        [THEME_KEY]: 'matrix',
        [VARS_CACHE_KEY]: JSON.stringify({ id: 'matrix', cssVars: MATRIX.cssVars }),
    });
    sandbox.Themes.applyStoredThemeIdSync();
    const afterFirst = style.setCalls.length;
    assert.ok(afterFirst > 0, 'the first paint must have set something');

    style.setCalls.length = 0;
    style.removeCalls.length = 0;
    sandbox.Themes.applyStoredThemeIdSync();
    assert.deepEqual(style.setCalls, [],
        'a re-apply of the identical palette must set nothing');
    assert.deepEqual(style.removeCalls, [],
        'a re-apply of the identical palette must remove nothing either');
});

await test('registry: switching themes still REMOVES every variable the outgoing one owned', () => {
    const wide = { '--color-bg': '#111111', '--agent-only-var': '#abcdef' };
    const narrow = { '--color-bg': '#111111' };
    const { sandbox, style, backing } = loadRegistry({
        [THEME_KEY]: 'wide',
        [VARS_CACHE_KEY]: JSON.stringify({ id: 'wide', cssVars: wide }),
    });
    sandbox.Themes.applyStoredThemeIdSync();
    assert.equal(style.values.get('--agent-only-var'), '#abcdef');
    assert.equal(style.values.get('--color-bg'), '#111111');

    style.setCalls.length = 0;
    style.removeCalls.length = 0;
    backing[THEME_KEY] = 'narrow';
    backing[VARS_CACHE_KEY] = JSON.stringify({ id: 'narrow', cssVars: narrow });
    sandbox.Themes.applyStoredThemeIdSync();

    assert.equal(style.values.has('--agent-only-var'), false,
        '--agent-only-var belonged only to the wide set and must be gone');
    assert.deepEqual(style.removeCalls, ['--agent-only-var']);
    assert.deepEqual(style.setCalls, [],
        'the one variable both sets share, at the same value, must not be re-set '
        + 'just because a different variable was dropped alongside it');
});

await test('registry: applyTheme still fires the xterm listener on EVERY call, even a no-op repaint', async () => {
    const { sandbox } = loadRegistry({});
    const xtermCalls = [];
    sandbox.Themes.onXtermThemeChange((p) => xtermCalls.push(p));

    sandbox.fetch = () => Promise.resolve({
        ok: true, status: 200, json: () => Promise.resolve([MATRIX, CLAUDE]),
    });
    await sandbox.Themes.init();
    xtermCalls.length = 0;

    sandbox.Themes.applyGlobal('matrix');
    assert.equal(xtermCalls.length, 1, 'the first apply must fire the xterm listener');

    sandbox.Themes.applyGlobal('matrix');
    assert.equal(xtermCalls.length, 2,
        'a repeated apply must still fire the xterm listener');
});

await test('registry: an unchanged VARS_CACHE_KEY write is skipped; a real change still writes', async () => {
    const { sandbox } = loadRegistry({});
    let setItemCalls = 0;
    const realSetItem = sandbox.localStorage.setItem;
    sandbox.localStorage.setItem = function (k, v) {
        if (k === 'carnivore.theme.vars') setItemCalls++;
        return realSetItem(k, v);
    };
    sandbox.fetch = () => Promise.resolve({
        ok: true, status: 200, json: () => Promise.resolve([MATRIX, CLAUDE]),
    });
    await sandbox.Themes.init();
    setItemCalls = 0;

    sandbox.Themes.applyGlobal('matrix');
    assert.equal(setItemCalls, 1, 'the first apply must cache the palette');

    sandbox.Themes.applyGlobal('matrix');
    assert.equal(setItemCalls, 1,
        're-applying the identical theme must not write the cache again');

    sandbox.Themes.applyGlobal('claude');
    assert.equal(setItemCalls, 2,
        'a real theme change must still write the cache');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
