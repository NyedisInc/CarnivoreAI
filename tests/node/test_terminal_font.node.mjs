// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client', 'js', 'terminal-font.js'), 'utf8');

const FACTORY_STACK = /fontFamily: '([^']+)'/.exec(fs.readFileSync(path.join(ROOT, 'client', 'js', 'terminal-client-factory.js'), 'utf8'))[1];

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

function page() {
    const storage = new Map();
    const loads = [];
    const ctx = {
        console: { log() {}, warn() {}, error: console.error },
        setTimeout, clearTimeout, WeakRef, Promise,
        CloudeTerminal: { XTERM_OPTIONS: { fontFamily: FACTORY_STACK } },
        localStorage: {
            getItem: (k) => (storage.has(k) ? storage.get(k) : null),
            setItem: (k, v) => storage.set(k, String(v)),
            removeItem: (k) => storage.delete(k),
        },
        document: { fonts: { load: (spec) => { loads.push(spec); return Promise.resolve([]); } } },
    };
    ctx.window = ctx;
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    return { TF: ctx.TerminalFont, loads, storage };
}

function fakeTerm(TF) {
    const t = { sets: 0, cleared: 0, options: {} };
    const o = TF.optionsFor();
    let size = o.fontSize;
    let fam = o.fontFamily;
    Object.defineProperty(t.options, 'fontSize', { get: () => size, set: (v) => { size = v; t.sets++; } });
    Object.defineProperty(t.options, 'fontFamily', { get: () => fam, set: (v) => { fam = v; t.sets++; } });
    for (const k of ['fontWeight', 'fontWeightBold']) {
        let v = o[k];
        Object.defineProperty(t.options, k, { get: () => v, set: (x) => { v = x; t.sets++; } });
    }
    t.clearTextureAtlas = () => { t.cleared++; };
    return t;
}

const settle = (TF) => new Promise((r) => setTimeout(r, TF.DEBOUNCE_MS + 30));

await test('a burst of steps applies once after the debounce: one option write and one refit per terminal', async () => {
    const { TF } = page();
    const terms = [fakeTerm(TF), fakeTerm(TF), fakeTerm(TF)];
    const fits = [0, 0, 0];
    terms.forEach((t, i) => TF.bind(t, (reason) => { assert.equal(reason, 'terminal-font'); fits[i]++; }));
    TF.step(1); TF.step(1); TF.step(1);
    assert.deepEqual(fits, [0, 0, 0], 'nothing before the debounce');
    await settle(TF);
    assert.deepEqual(fits, [1, 1, 1]);
    assert.deepEqual(terms.map((t) => t.sets), [1, 1, 1], 'one atlas rebuild each (only fontSize moved)');
    assert.deepEqual(terms.map((t) => t.options.fontSize), [17, 17, 17]);
    TF.setSize(17);
    await settle(TF);
    assert.deepEqual(fits, [1, 1, 1]);
});

await test('weight: four numeric choices, default normal, optionsFor carries them, a live terminal restyles once, an unknown name is normal', async () => {
    const { TF, storage } = page();
    assert.equal(TF.weight(), 'normal');
    assert.deepEqual([TF.optionsFor().fontWeight, TF.optionsFor().fontWeightBold], [400, 700]);
    const term = fakeTerm(TF);
    let fits = 0;
    TF.bind(term, () => { fits++; });
    assert.equal(TF.setWeight('light'), 'light');
    await settle(TF);
    assert.equal(storage.get('carnivore.terminal-font-weight'), 'light');
    assert.deepEqual([term.options.fontWeight, term.options.fontWeightBold, fits], [300, 600, 1]);
    for (const [name, w, b] of [['medium', 500, 700], ['bold', 700, 800]]) {
        TF.setWeight(name);
        assert.deepEqual([TF.optionsFor().fontWeight, TF.optionsFor().fontWeightBold], [w, b]);
    }
    assert.equal(TF.setWeight('heavy'), 'normal');
    assert.equal(storage.has('carnivore.terminal-font-weight'), false);
});

await test('the size is clamped to 9..28 and the default is stored as nothing', () => {
    const { TF, storage } = page();
    assert.equal(TF.size(), 14);
    assert.equal(TF.setSize(99), 28);
    assert.equal(TF.setSize(-3), 9);
    assert.equal(TF.setSize('abc'), 14);
    assert.equal(storage.has('carnivore.terminal-font-size'), false);
    assert.equal(TF.clampSize(15.6), 16);
    for (let i = 0; i < 30; i++) TF.step(-1);
    assert.equal(TF.size(), 9);
});

await test('a family name cannot carry CSS: quotes, semicolons, commas, braces, slashes and 201 characters are refused', async () => {
    const { TF, storage, loads } = page();
    for (const bad of ['a"b', "a'b", 'x; color: red', 'a,b', 'a{b}', 'a\\b', '<x>', 'a\u0000b', 'x'.repeat(201)]) {
        assert.equal(TF.sanitizeFamily(bad), '', JSON.stringify(bad));
        assert.equal(await TF.setFamily(bad), false);
    }
    assert.equal(storage.has('carnivore.terminal-font-family'), false);
    assert.equal(loads.length, 0, 'a refused name is never loaded');
    assert.equal(await TF.setFamily('  JetBrains Mono  '), true);
    assert.equal(TF.family(), 'JetBrains Mono');
    assert.ok(loads.includes('400 14px "JetBrains Mono"'), 'loaded before it is applied');
    assert.equal(await TF.setFamily(''), true);
    assert.equal(TF.family(), '');
});

await test('every font stack ends with the platform monospace fonts, the icon font, then monospace', () => {
    const { TF } = page();
    const tail = ', "Courier New", "SymbolsNerdFontMono", monospace';
    assert.ok(TF.familyStack('').endsWith(tail));
    assert.ok(TF.familyStack('Fira Code').startsWith('"Fira Code", ui-monospace'));
    assert.ok(TF.familyStack('Fira Code').endsWith(tail));
    assert.ok(TF.familyStack('bad;"name').startsWith('ui-monospace'), 'a refused name falls back to the platform stack');
    assert.equal(TF.familyStack('', 'Menlo, monospace'), 'Menlo, "SymbolsNerdFontMono", monospace');
});

await test('binding loads the icon font once and re-bakes the atlas of every terminal when it lands', async () => {
    const { TF, loads } = page();
    const a = fakeTerm(TF);
    const b = fakeTerm(TF);
    TF.bind(a);
    TF.bind(b);
    assert.equal(loads.filter((s) => s.includes('SymbolsNerdFontMono')).length, 1);
    await new Promise((r) => setTimeout(r, 0));
    assert.deepEqual([a.cleared, b.cleared], [1, 1]);
});

console.log(failures ? `${failures} FAILED, ${passes} passed` : `ALL PASS (${passes})`);
process.exit(failures ? 1 : 0);
