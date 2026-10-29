
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const THEME_KEY = 'carnivore.theme';
const VARS_CACHE_KEY = 'carnivore.theme.vars';

let passes = 0;
let failures = 0;

/**
 * Description: run one named assertion block, recording rather than
 *   throwing so one failure does not hide the rest.
 * Inputs: name (string), fn (function). Output: Promise<void>.
 */
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

function load(store) {
    const painted = new Map();
    const backing = { ...store };
    const rootStyle = {
        setProperty(name, value) { painted.set(name, value); },
        removeProperty(name) { painted.delete(name); },
    };
    const documentElement = { style: rootStyle, dataset: {} };
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
    return { sandbox, painted, dataset: documentElement.dataset, backing };
}

function manifest(id) {
    return JSON.parse(fs.readFileSync(
        path.join(ROOT, 'client', 'css', 'themes', id, 'theme.json'), 'utf8'));
}

const MATRIX = manifest('matrix');
const CLAUDE = manifest('claude');

await test('the two themes actually differ, or nothing below discriminates', () => {
    for (const token of ['--color-bg', '--color-accent', '--color-fg']) {
        assert.notEqual(MATRIX.cssVars[token], CLAUDE.cssVars[token],
            `matrix and claude agree on ${token}; it cannot tell them apart`);
    }
});

await test('the harness records painted vars (positive control)', () => {
    const { sandbox, painted } = load({});
    sandbox.Themes.applyStoredThemeIdSync();
    // through a real
    assert.equal(painted.size, 0, 'no cache must paint nothing');
    const seeded = load({
        [THEME_KEY]: 'matrix',
        [VARS_CACHE_KEY]: JSON.stringify({ id: 'matrix', cssVars: MATRIX.cssVars }),
    });
    seeded.sandbox.Themes.applyStoredThemeIdSync();
    assert.ok(seeded.painted.size > 0,
        'the style recorder captured nothing at all - every assertion below '
        + 'would pass for the wrong reason');
});

await test('a cached palette is painted before auth', () => {
    const { sandbox, painted, dataset } = load({
        [THEME_KEY]: 'matrix',
        [VARS_CACHE_KEY]: JSON.stringify({ id: 'matrix', cssVars: MATRIX.cssVars }),
    });
    sandbox.Themes.applyStoredThemeIdSync();
    assert.equal(dataset.theme, 'matrix', 'the attribute must still be set');
    assert.equal(painted.get('--color-bg'), MATRIX.cssVars['--color-bg']);
    assert.equal(painted.get('--color-accent'), MATRIX.cssVars['--color-accent']);
    assert.notEqual(painted.get('--color-bg'), CLAUDE.cssVars['--color-bg'],
        'the login screen is still showing the default palette');
});

await test('a cache written for ANOTHER theme is never painted', () => {
    const { sandbox, painted } = load({
        [THEME_KEY]: 'matrix',
        [VARS_CACHE_KEY]: JSON.stringify({ id: 'claude', cssVars: CLAUDE.cssVars }),
    });
    sandbox.Themes.applyStoredThemeIdSync();
    assert.equal(painted.size, 0,
        'a palette cached for claude was painted while matrix was stored - '
        + 'the user would see colours they never chose');
});

await test('a corrupt or absent cache falls back to the defaults, silently', () => {
    for (const raw of ['not json at all', '{"id":"matrix"}', '[]', 'null']) {
        const { sandbox, painted } = load({ [THEME_KEY]: 'matrix', [VARS_CACHE_KEY]: raw });
        assert.doesNotThrow(() => sandbox.Themes.applyStoredThemeIdSync(),
            `applyStoredThemeIdSync threw on cache ${raw} - this runs on the '
            + 'pre-auth path where a throw means a blank page`);
        assert.equal(painted.size, 0, `cache ${raw} should paint nothing`);
    }
});

await test('a real init() writes the cache the next load reads', async () => {
    const { sandbox, backing } = load({ [THEME_KEY]: 'matrix' });
    sandbox.fetch = () => Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve([MATRIX, CLAUDE]),
    });
    await sandbox.Themes.init();
    const cached = JSON.parse(backing[VARS_CACHE_KEY] || '{}');
    assert.equal(cached.id, 'matrix',
        'init() applied the theme but cached no palette, so the next login '
        + 'screen has nothing to paint');
    assert.equal(cached.cssVars['--color-bg'], MATRIX.cssVars['--color-bg']);
});

await test('the cache init() writes is the one applyStoredThemeIdSync reads', async () => {
    const first = load({ [THEME_KEY]: 'matrix' });
    first.sandbox.fetch = () => Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve([MATRIX, CLAUDE]),
    });
    await first.sandbox.Themes.init();

    const second = load({ ...first.backing });
    second.sandbox.Themes.applyStoredThemeIdSync();
    assert.equal(second.painted.get('--color-bg'), MATRIX.cssVars['--color-bg'],
        'the login screen did not paint the palette the last session cached');
    assert.notEqual(second.painted.get('--color-bg'), CLAUDE.cssVars['--color-bg']);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
