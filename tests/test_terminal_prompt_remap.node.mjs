
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const CLIENT_JS = path.join(ROOT, 'client', 'js');
const THEMES = path.join(ROOT, 'client', 'css', 'themes');

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

function makeSandbox(withRemap = true) {
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const context = {
        window: fakeWindow,
        document: { documentElement: { dataset: {} } },
        console,
        MutationObserver: class { observe() {} disconnect() {} },
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(CLIENT_JS, 'terminal-background-opacity.js'), 'utf8'), context);
    if (withRemap) {
        vm.runInContext(fs.readFileSync(path.join(CLIENT_JS, 'terminal-prompt-remap.js'), 'utf8'), context);
    }
    return fakeWindow;
}

function bundledXtermThemes() {
    const out = {};
    for (const id of fs.readdirSync(THEMES)) {
        const file = path.join(THEMES, id, 'theme.json');
        if (!fs.existsSync(file)) continue;
        const xterm = JSON.parse(fs.readFileSync(file, 'utf8')).xterm;
        if (xterm) out[id] = xterm;
    }
    return out;
}

const win = makeSandbox();
const shared = win.TerminalBackgroundOpacity;
const remap = win.TerminalPromptRemap;
const BG = 237 - 16;
const FG = 231 - 16;

function contrast(a, b) {
    const la = shared.relativeLuminance(shared.parseCssColorChannels(a));
    const lb = shared.relativeLuminance(shared.parseCssColorChannels(b));
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const themes = bundledXtermThemes();
const light = themes['carnivore-light'];
const dark = themes['carnivore'];

test('population: both reference themes exist and classify as expected', () => {
    assert.ok(Object.keys(themes).length > 10, 'bundled themes were read');
    assert.ok(light && dark, 'carnivore-light and carnivore manifests exist');
    assert.equal(shared.isLightXtermTheme(light), true);
    assert.equal(shared.isLightXtermTheme(dark), false);
});

test('the named constant carries Claude Code\'s measured slots', () => {
    assert.equal(remap.CLAUDE_DARK_PROMPT_SLOTS.background, 237);
    assert.equal(remap.CLAUDE_DARK_PROMPT_SLOTS.foreground, 231);
});

test('carnivore-light: slot 237 becomes a soft band, slot 231 the ink, >= 7:1', () => {
    const out = remap.withLightPromptRemap(light);
    assert.notEqual(out, light, 'a copy, never a mutation of the manifest');
    assert.equal(light.extendedAnsi, undefined, 'manifest left untouched');
    const band = out.extendedAnsi[BG];
    assert.equal(out.extendedAnsi[FG], light.foreground);
    const groundVsBand = contrast(light.background, band);
    assert.ok(groundVsBand > 1.05 && groundVsBand < 1.4,
        `band is slightly darker than the ground, got ${groundVsBand.toFixed(2)}:1 (${band})`);
    assert.ok(contrast(light.foreground, band) >= 7,
        `ink on band ${contrast(light.foreground, band).toFixed(2)}:1`);
});

test('only slots 237 and 231 are filled; every other slot falls back to xterm', () => {
    const out = remap.withLightPromptRemap(light);
    const filled = Object.keys(out.extendedAnsi).map(Number).sort((a, b) => a - b);
    assert.deepEqual(filled, [FG, BG]);
});

test('an authored extendedAnsi is kept for every other slot', () => {
    const authored = Object.assign({}, light, { extendedAnsi: ['#010203'] });
    const out = remap.withLightPromptRemap(authored);
    assert.equal(out.extendedAnsi[0], '#010203');
    assert.deepEqual(authored.extendedAnsi, ['#010203'], 'authored array not mutated');
});

test('every bundled DARK theme passes through as the same object', () => {
    let darkCount = 0;
    for (const [id, xterm] of Object.entries(themes)) {
        if (shared.isLightXtermTheme(xterm)) continue;
        darkCount++;
        assert.equal(remap.withLightPromptRemap(xterm), xterm, id);
    }
    assert.ok(darkCount > 10, 'dark themes were actually checked');
});

test('every bundled LIGHT theme gets ink on band >= 7:1', () => {
    let lightCount = 0;
    for (const [id, xterm] of Object.entries(themes)) {
        if (!shared.isLightXtermTheme(xterm)) continue;
        lightCount++;
        const out = remap.withLightPromptRemap(xterm);
        assert.ok(contrast(xterm.foreground, out.extendedAnsi[BG]) >= 7, id);
    }
    assert.ok(lightCount >= 1, 'at least one light theme was checked');
});

test('absent or unparseable themes come back unchanged', () => {
    assert.equal(remap.withLightPromptRemap(null), null);
    const odd = { background: 'papayawhip', foreground: '#000' };
    assert.equal(remap.withLightPromptRemap(odd), odd);
});

function fakeTerm() {
    return { options: {} };
}

test('the shared funnel applies it and a live light -> dark switch drops it', () => {
    const term = fakeTerm();
    const handle = shared.attach(term);
    handle.apply(light);
    assert.equal(term.options.theme.extendedAnsi[BG], remap.withLightPromptRemap(light).extendedAnsi[BG]);
    handle.apply(dark);
    assert.equal(term.options.theme, dark, 'dark theme reaches xterm as the same object');
    assert.equal(term.options.theme.extendedAnsi, undefined);
    handle.apply(light);
    assert.ok(term.options.theme.extendedAnsi, 'switching back re-applies it');
});

test('negative control: without the remap module the funnel leaves the slab alone', () => {
    const bare = makeSandbox(false);
    const term = fakeTerm();
    bare.TerminalBackgroundOpacity.attach(term).apply(light);
    assert.equal(term.options.theme.extendedAnsi, undefined);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures || !passes) process.exit(1);
