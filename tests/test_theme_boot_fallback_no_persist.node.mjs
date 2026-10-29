
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const THEME_KEY = 'carnivore.theme';

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

async function settle() {
    for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r));
}

async function boot({ serverTheme, themes, local }) {
    const patches = [];
    const timers = [];
    const backing = {};
    if (local) backing[THEME_KEY] = local;
    let answer = themes;
    const documentElement = {
        style: { setProperty() {}, removeProperty() {} },
        dataset: {},
    };
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, info() {} },
        document: {
            documentElement,
            readyState: 'complete',
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
        setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
        clearTimeout: () => {},
        setInterval: () => 0, clearInterval: () => {},
        fetch: async (url) => {
            if (!String(url).includes('/api/v1/themes')) {
                return { ok: true, status: 200, json: async () => ({}) };
            }
            if (answer === 'fail') return { ok: false, status: 503, json: async () => ({}) };
            return {
                ok: true, status: 200,
                json: async () => answer.map((id) => ({ id, name: id, cssVars: {}, xterm: {} })),
            };
        },
        API: {
            async call(p, opts) {
                if (p === '/preferences' && (!opts || !opts.method)) {
                    return { revision: 7, values: serverTheme ? { theme: serverTheme } : {} };
                }
                if (p === '/preferences' && opts.method === 'PATCH') {
                    patches.push(opts.body.changes);
                    return { revision: 8, values: { ...opts.body.changes }, status: 'committed' };
                }
                throw new Error('unexpected API call ' + p);
            },
        },
        ResourcePush: { onChange: () => () => {} },
        Set, Map, JSON, Object, Array, Promise, Error, Number, String,
        location: { href: '' }, navigator: { userAgent: '' },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    for (const f of ['theme-var-writer.js', 'preferences.js', 'preference-bridge.js',
        'themes/registry.js']) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, 'client', 'js', f), 'utf8'),
            sandbox, { filename: f });
    }
    const st = await sandbox.Preferences.hydrate(sandbox.API);
    assert.equal(st, sandbox.Preferences.HYDRATED, 'harness: preferences must hydrate');
    await sandbox.Themes.init();
    await settle();
    return {
        sandbox, patches, dataset: documentElement.dataset, backing, timers,
        setThemes: (v) => { answer = v; },
    };
}

const IDS = ['carnivore', 'alien', 'matrix'];

await test('(a) /api/v1/themes fails: paints the fallback, writes nothing', async () => {
    const r = await boot({ serverTheme: 'alien', themes: 'fail' });
    assert.equal(r.dataset.theme, 'carnivore', 'the page must still be usable');
    assert.deepEqual(r.patches, [], 'a fallback paint must not PATCH the global theme');
    assert.equal(r.backing[THEME_KEY], undefined,
        'the fallback must not overwrite the local paint hint either');
});

await test('(a) a later successful /themes load repaints the server theme', async () => {
    const r = await boot({ serverTheme: 'alien', themes: 'fail' });
    assert.ok(r.timers.length > 0, 'a failed load must schedule a retry');
    r.setThemes(IDS);
    r.timers.shift().fn();
    await settle();
    assert.equal(r.dataset.theme, 'alien', 'the recovered list must repaint the real theme');
    assert.deepEqual(r.patches, [], 'the recovery repaint is not a choice either');
});

await test('(b) saved theme not installed: paints the fallback, keeps the stored id', async () => {
    const r = await boot({ serverTheme: 'alien', themes: ['carnivore', 'matrix'] });
    assert.equal(r.dataset.theme, 'carnivore');
    assert.deepEqual(r.patches, [], 'an uninstalled theme must not be overwritten');
    assert.equal(r.sandbox.Preferences.get('theme', null), 'alien',
        'the stored global theme id must survive');
    assert.equal(r.timers.length, 0, 'a list that loaded is not retried');
});

await test('(c) normal load paints the server theme and writes nothing', async () => {
    const r = await boot({ serverTheme: 'alien', themes: IDS, local: 'matrix' });
    assert.equal(r.dataset.theme, 'alien');
    assert.deepEqual(r.patches, [], 'a boot paint is not a user choice');
    assert.equal(r.backing[THEME_KEY], 'alien', 'the local paint hint follows the server');
});

await test('a user gesture still writes the global theme (positive control)', async () => {
    const r = await boot({ serverTheme: 'alien', themes: IDS });
    r.sandbox.Themes.applyGlobal('matrix');
    await settle();
    assert.equal(JSON.stringify(r.patches), JSON.stringify([{ theme: 'matrix' }]),
        'the PATCH recorder saw nothing; every "no PATCH" above would pass for the wrong reason');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
