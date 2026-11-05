
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SOURCE = fs.readFileSync(path.join(ROOT, 'client', 'js', 'theme-scheme.js'), 'utf8');

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

function stubContext() {
    let fill = '#000000';
    let pixel = [0, 0, 0, 0];
    return {
        get fillStyle() { return fill; },
        set fillStyle(v) { if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(v)) fill = v.toLowerCase(); },
        clearRect() { pixel = [0, 0, 0, 0]; },
        fillRect() {
            const n = (i) => parseInt(fill.slice(i, i + 2), 16);
            pixel = [n(1), n(3), n(5), fill.length === 9 ? n(7) : 255];
        },
        getImageData() { return { data: Uint8ClampedArray.from(pixel) }; },
    };
}

function load({ canvas = true, line = '0.6' } = {}) {
    const sandbox = { Math, Map, Number, isFinite, Uint8ClampedArray, Object, String };
    sandbox.globalThis = sandbox;
    if (canvas) sandbox.OffscreenCanvas = function OffscreenCanvas() { return { getContext: () => stubContext() }; };
    sandbox.document = { documentElement: {} };
    sandbox.getComputedStyle = () => ({ getPropertyValue: (name) => (name === '--oc-light-line-l' ? line : '') });
    vm.createContext(sandbox);
    vm.runInContext(SOURCE, sandbox, { filename: 'theme-scheme.js' });
    return sandbox.ThemeScheme;
}

const near = (got, want, eps = 0.001) => assert.ok(Math.abs(got - want) < eps, `${got} is not about ${want}`);

test('oklab lightness of known colors: white 1, black 0, #808080 about 0.6', () => {
    const s = load();
    near(s.oklabLightness(255, 255, 255), 1);
    near(s.oklabLightness(0, 0, 0), 0);
    near(s.oklabLightness(128, 128, 128), 0.5999);
});

test('a light and a dark shipped ground', () => {
    const s = load();
    assert.equal(s.withColorScheme({ '--color-bg-page': '#eceeef' })['--color-scheme'], 'light'); // carnivore-light
    assert.equal(s.withColorScheme({ '--color-bg-page': '#282a36' })['--color-scheme'], 'dark'); // dracula
});

test('the page ground is read before the card ground', () => {
    const s = load();
    assert.equal(s.withColorScheme({ '--color-bg-page': '#ffffff', '--color-bg': '#000000' })['--color-scheme'], 'light');
    assert.equal(s.withColorScheme({ '--color-bg': '#000000' })['--color-scheme'], 'dark');
});

test('transparent, currentColor and a see-through pixel answer null: the set is left alone', () => {
    const s = load();
    for (const ground of ['transparent', 'currentColor', 'CurrentColor', '#ffffff80', 'not a color']) {
        const vars = { '--color-bg-page': ground };
        assert.equal(s.withColorScheme(vars), vars, ground);
        assert.equal(s.schemeOfColor(ground), null, ground);
    }
    assert.equal(s.schemeOfPixel([255, 255, 255, 254], 0.6), null);
});

test('an explicit scheme, a set with no ground, no canvas and no line all leave the set alone', () => {
    const s = load();
    const named = { '--color-bg-page': '#ffffff', '--color-scheme': 'dark' };
    assert.equal(s.withColorScheme(named), named);
    const bare = { '--color-accent': '#ff0000' };
    assert.equal(s.withColorScheme(bare), bare);
    const noCanvas = load({ canvas: false });
    assert.equal(noCanvas.schemeOfColor('#ffffff'), null);
    const noLine = load({ line: '' });
    assert.equal(noLine.schemeOfColor('#ffffff'), null);
});

test('the line is the stylesheet one: a higher line turns a mid ground dark', () => {
    assert.equal(load({ line: '0.5' }).schemeOfColor('#808080'), 'light');
    assert.equal(load({ line: '0.7' }).schemeOfColor('#808080'), 'dark');
});

test('no OffscreenCanvas (iOS before 16.4): the registered element canvas reads the ground; none registered answers null, uncached', () => {
    const s = load({ canvas: false });
    assert.equal(s.schemeOfColor('#eceeef'), null);
    let made = 0;
    s.useCanvas(() => { made++; return { width: 0, height: 0, getContext: () => stubContext() }; });
    assert.equal(s.schemeOfColor('#eceeef'), 'light');
    assert.equal(s.schemeOfColor('#282a36'), 'dark');
    assert.equal(made, 2);
});

test('the cache stays bounded', () => {
    const s = load();
    for (let i = 0; i < 200; i++) s.schemeOfColor(`#${i.toString(16).padStart(6, '0')}`);
    assert.equal(s.schemeOfColor('#ffffff'), 'light');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
