import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const THEME_KEY = 'carnivore.theme';
const VARS_KEY = 'carnivore.theme.vars';
let failures = 0;

async function test(name, fn) {
    try { await fn(); console.log(`ok - ${name}`); } catch (e) { failures++; console.error(`NOT OK - ${name}\n${e.stack}`); }
}

const bundled = (id) => JSON.parse(fs.readFileSync(path.join(ROOT, 'client/css/themes', id, 'theme.json'), 'utf8'));
const CARNIVORE = bundled('carnivore');
const MATRIX = bundled('matrix');

function load(store, routes) {
    const painted = new Map(), backing = { ...store }, urls = [];
    const dataset = {};
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: {
            documentElement: { dataset, style: {
                setProperty: (n, v) => painted.set(n, v), removeProperty: (n) => painted.delete(n) } },
            createElement: () => ({ style: {}, setAttribute() {}, appendChild() {} }),
            head: { appendChild() {} }, addEventListener() {}, removeEventListener() {},
            getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
        },
        localStorage: {
            getItem: (k) => (k in backing ? backing[k] : null),
            setItem: (k, v) => { backing[k] = String(v); }, removeItem: (k) => { delete backing[k]; },
        },
        setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
        fetch: (url) => {
            urls.push(url);
            const r = routes[url];
            if (!r) return Promise.reject(new Error('no route ' + url));
            return Promise.resolve(typeof r === 'function' ? r() : r).then((v) => ({
                ok: v.ok, status: v.ok ? 200 : 404, json: async () => v.body }));
        },
        Set, Map, JSON, Object, Array, Promise, Error, encodeURIComponent,
        location: { href: '' }, navigator: { userAgent: '' },
    };
    sandbox.window = sandbox; sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    for (const f of ['client/js/theme-var-writer.js', 'client/js/themes/registry.js']) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), sandbox, { filename: f });
    }
    return { sandbox, painted, dataset, backing, urls };
}

const flush = () => new Promise((r) => setImmediate(r));
const url = (id) => '/static/css/themes/' + encodeURIComponent(id) + '/theme.json';
const good = (m) => ({ ok: true, body: m });
const cached = (h) => JSON.parse(h.backing[VARS_KEY] || 'null');

await test('T1 no cache: bundled carnivore vars painted and cached', async () => {
    const h = load({ [THEME_KEY]: 'carnivore' }, { [url('carnivore')]: good(CARNIVORE) });
    h.sandbox.Themes.applyStoredThemeIdSync();
    assert.equal(h.painted.size, 0, 'sync paint stays empty');
    await flush();
    assert.equal(h.painted.get('--color-bg'), CARNIVORE.cssVars['--color-bg']);
    assert.equal(cached(h).id, 'carnivore');
    assert.ok(Object.keys(cached(h).cssVars).length > 0);
});

await test('T2 degraded cache {} is treated as no cache', async () => {
    const h = load({ [THEME_KEY]: 'carnivore', [VARS_KEY]: JSON.stringify({ id: 'carnivore', cssVars: {} }) },
        { [url('carnivore')]: good(CARNIVORE) });
    h.sandbox.Themes.applyStoredThemeIdSync();
    await flush();
    assert.equal(h.painted.get('--color-bg'), CARNIVORE.cssVars['--color-bg']);
});

await test('T3 matrix 404 falls back to carnivore, cached under carnivore', async () => {
    const h = load({ [THEME_KEY]: 'matrix' }, { [url('matrix')]: { ok: false }, [url('carnivore')]: good(CARNIVORE) });
    h.sandbox.Themes.applyStoredThemeIdSync();
    await flush();
    assert.equal(cached(h).id, 'carnivore');
    assert.equal(h.painted.get('--color-bg'), CARNIVORE.cssVars['--color-bg']);
});

await test('T4 late paint after init() is dropped', async () => {
    let release;
    const held = new Promise((r) => { release = r; });
    const h = load({ [THEME_KEY]: 'alien' }, {
        [url('alien')]: () => held.then(() => good({ ...MATRIX, id: 'alien' })),
        '/api/v1/themes': good([MATRIX, CARNIVORE]),
    });
    h.sandbox.Themes.applyStoredThemeIdSync();
    h.backing[THEME_KEY] = 'matrix';
    await h.sandbox.Themes.init();
    const before = new Map(h.painted), theme = h.dataset.theme;
    release(); await flush(); await flush();
    assert.deepEqual([...h.painted], [...before]);
    assert.equal(h.dataset.theme, theme);
    assert.notEqual((cached(h) || {}).id, 'alien');
});

await test('T5 bad bodies paint and cache nothing', async () => {
    for (const body of [{}, { ...CARNIVORE, cssVars: [] }, { ...CARNIVORE, id: 'other' }]) {
        const h = load({ [THEME_KEY]: 'carnivore' }, { [url('carnivore')]: good(body) });
        h.sandbox.Themes.applyStoredThemeIdSync();
        await flush();
        assert.equal(h.painted.size, 0);
        assert.equal(h.backing[VARS_KEY], undefined);
    }
});

const ACCEPTED = ['matrix', 'claude', 'Neon Rain', '_lead', 'a.b-c_d', 'a  b', 'ab', 'a', 'x'.repeat(128)];
const REFUSED = ['x'.repeat(129), 'über', 'a​b', 'a‮b', ' lead', 'trail ', '.hidden', '.', '..', '-flag',
    'a/b', 'a\\b', 'a\u0000b', 'a\nb', 'matrix\n', '', '../x'];
await test('T6 id rule', async () => {
    for (const id of ACCEPTED) {
        const h = load({ [THEME_KEY]: id }, {});
        h.sandbox.Themes.applyStoredThemeIdSync();
        await flush();
        assert.equal(h.urls[0], url(id), id);
    }
    for (const id of REFUSED) {
        const h = load({ [THEME_KEY]: id }, { [url('carnivore')]: good(CARNIVORE) });
        h.sandbox.Themes.applyStoredThemeIdSync();
        await flush();
        assert.deepEqual(h.urls.filter((u) => u !== url('carnivore')), [], JSON.stringify(id));
    }
});

await test('T7 loadManifests API failure: static carnivore fallback, xterm kept, good cache kept', async () => {
    const goodCache = JSON.stringify({ id: 'carnivore', cssVars: CARNIVORE.cssVars });
    const h = load({ [THEME_KEY]: 'carnivore', [VARS_KEY]: goodCache }, { [url('carnivore')]: good(CARNIVORE) });
    let seen = null;
    h.sandbox.Themes.onXtermThemeChange((x) => { seen = x; });
    await h.sandbox.Themes.init();
    assert.deepEqual(seen, CARNIVORE.xterm);
    assert.equal(h.painted.get('--color-bg'), CARNIVORE.cssVars['--color-bg']);
    const h2 = load({ [THEME_KEY]: 'carnivore', [VARS_KEY]: goodCache }, {});
    await h2.sandbox.Themes.init();
    assert.equal(h2.backing[VARS_KEY], goodCache);
});

process.exit(failures ? 1 : 0);
