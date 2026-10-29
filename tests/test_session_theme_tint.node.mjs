// the home screen

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

function parseColor(text) {
    const s = String(text).trim();
    if (s.startsWith('#')) {
        let h = s.slice(1);
        if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
        const n = parseInt(h, 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
    }
    const m = s.match(/rgba?\(([^)]*)\)/);
    assert.ok(m, `unparseable colour: ${text}`);
    const p = m[1].split(',').map((x) => parseFloat(x));
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
}

function luminance(c) {
    const f = (v) => {
        const x = v / 255;
        return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}

function contrast(a, b) {
    const l1 = luminance(a);
    const l2 = luminance(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

const BASE_CSS = fs.readFileSync(path.join(ROOT, 'client', 'css', 'styles.css'), 'utf8');

function rootVar(name) {
    const m = BASE_CSS.match(new RegExp(`${name}:\\s*([^;]+);`));
    assert.ok(m, `${name} is not declared in styles.css :root`);
    return m[1].trim();
}

const THEME_DIR = path.join(ROOT, 'client', 'css', 'themes');
const THEMES = fs.readdirSync(THEME_DIR)
    .filter((d) => fs.existsSync(path.join(THEME_DIR, d, 'theme.json')))
    .map((d) => JSON.parse(fs.readFileSync(path.join(THEME_DIR, d, 'theme.json'), 'utf8')));

function load(manifests) {
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    if (manifests !== null) {
        sandbox.Themes = { listAll: () => manifests };
    }
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(path.join(ROOT, 'client', 'js', 'session-theme-tint.js'), 'utf8'),
        sandbox,
    );
    return sandbox;
}

const tint = load(THEMES).SessionThemeTint;
const tintCss = fs.readFileSync(path.join(ROOT, 'client', 'css', 'session-theme-tint.css'), 'utf8');

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

const GRAPHIC_FLOOR = 3.0;

function pageBg(vars) {
    return parseColor(vars['--color-bg']);
}

function hairline(vars) {
    return parseColor(vars['--color-fg-subtle'] || rootVar('--color-fg-subtle'));
}

test('the sweep covers every theme pair, so it is not a spot check', () => {
    assert.ok(THEMES.length >= 12, `expected 12+ themes, found ${THEMES.length}`);
    for (const t of THEMES) {
        for (const v of ['--color-bg', '--color-fg', '--color-accent']) {
            assert.ok(t.cssVars && t.cssVars[v], `${t.id} is missing ${v}`);
        }
        assert.ok(pageBg(t.cssVars).every((v) => Number.isFinite(v)),
            `${t.id} --color-bg did not resolve to a colour`);
        assert.ok(hairline(t.cssVars).every((v) => Number.isFinite(v)),
            `${t.id} has no usable --color-fg-subtle`);
    }
});

test('the swatch FILL alone is not always visible, which is why it has a hairline', () => {
    const dim = [];
    for (const host of THEMES) {
        const bg = pageBg(host.cssVars);
        for (const session of THEMES) {
            const fill = parseColor(session.cssVars['--color-accent']);
            if (contrast(fill, bg) < GRAPHIC_FLOOR) {
                dim.push(`${host.id}/${session.id}`);
            }
        }
    }
    assert.ok(dim.length > 0,
        'no (host, session) pair renders a low-contrast swatch fill; if that is '
        + 'now true the hairline needs re-justifying rather than silently keeping');
});

test('the hairline clears 3:1 in every theme, so the swatch is always locatable', () => {
    const broken = [];
    for (const host of THEMES) {
        const ratio = contrast(hairline(host.cssVars), pageBg(host.cssVars));
        if (ratio < GRAPHIC_FLOOR) {
            broken.push(`${host.id} ${ratio.toFixed(2)}`);
        }
    }
    assert.deepEqual(broken, [],
        'these themes draw the swatch hairline below the 3:1 non-text floor '
        + 'against their own page, so a low-contrast accent there is an '
        + 'invisible swatch and the cue silently disappears');
});

test('no (host, session) pair leaves BOTH the fill and the hairline under 3:1', () => {
    const blind = [];
    for (const host of THEMES) {
        const bg = pageBg(host.cssVars);
        const edge = contrast(hairline(host.cssVars), bg);
        for (const session of THEMES) {
            const fill = contrast(parseColor(session.cssVars['--color-accent']), bg);
            if (fill < GRAPHIC_FLOOR && edge < GRAPHIC_FLOOR) {
                blind.push(`${host.id}/${session.id}`);
            }
        }
    }
    assert.deepEqual(blind, [],
        'these pairs render a swatch no one can see, in either layer');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('a themed row carries the theme id and ONE colour, and nothing else', () => {
    const out = tint.attrs('dracula');
    assert.match(out, /data-session-theme="dracula"/);
    assert.match(out, /--session-theme-accent: rgb\(189, 147, 249\)/);
    assert.doesNotMatch(out, /--session-theme-wash/);
    assert.doesNotMatch(out, /--session-theme-ring/);
});

test('a themed row gets a swatch, and it says what it is in words', () => {
    const html = tint.swatchHtml('dracula');
    assert.match(html, /class="session-theme-swatch"/);
    assert.match(html, /role="img"/);
    assert.match(html, /aria-label="session theme: Dracula"/);
    assert.match(html, /title="session theme: Dracula"/);
});

test('the swatch takes its name from the manifest, and falls back to the id', () => {
    const sandbox = load([{ id: 'nameless', cssVars: { '--color-accent': '#112233' } }]);
    const html = sandbox.SessionThemeTint.swatchHtml('nameless');
    assert.match(html, /aria-label="session theme: nameless"/,
        'a manifest with no display name must still produce a named cue, not an '
        + 'empty one');
});

test('a display name cannot break out of the attribute it is written into', () => {
    const sandbox = load([{
        id: 'evil',
        name: 'a" onload="alert(1)',
        cssVars: { '--color-accent': '#112233' },
    }]);
    const html = sandbox.SessionThemeTint.swatchHtml('evil');
    assert.doesNotMatch(html, /onload="/,
        'an unescaped quote would close aria-label and open a real handler');
    assert.match(html, /&quot;/, 'the quote must be escaped, not dropped');
});

test('all three not-themed cases render exactly as today', () => {
    for (const fn of ['attrs', 'swatchHtml']) {
        assert.equal(tint[fn](null), '', `${fn}: no theme set`);
        assert.equal(tint[fn](undefined), '', `${fn}: field absent`);
        assert.equal(tint[fn]('no-such-theme'), '',
            `${fn}: id the registry does not know`);
        const noRegistry = load(null).SessionThemeTint;
        assert.equal(noRegistry[fn]('dracula'), '',
            `${fn}: the registry loads asynchronously; an early paint must `
            + 'degrade to the plain row, never to a default colour');
    }
});

test('an unknown id is not cached, because the registry fills in later', () => {
    const sandbox = load([]);
    assert.equal(sandbox.SessionThemeTint.attrs('dracula'), '');
    sandbox.Themes.listAll = () => THEMES;
    assert.match(sandbox.SessionThemeTint.attrs('dracula'), /data-session-theme/,
        'a miss must stay askable on the next paint');
});

test('a theme id cannot break out of the attribute it is written into', () => {
    for (const fn of ['attrs', 'swatchHtml']) {
        assert.equal(tint[fn]('dracula" onload="alert(1)'), '',
            `${fn}: the id is scrubbed to [A-Za-z0-9_-], and a scrubbed id that `
            + 'does not match a manifest yields nothing at all');
    }
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

function liveTintCss() {
    return tintCss.split('\n')
        .filter((l) => !l.trim().startsWith('*') && !l.trim().startsWith('/*'))
        .join('\n');
}

test('nothing in this file selects a session ROW any more', () => {
    const live = liveTintCss();
    assert.doesNotMatch(live, /\.session-sidebar-row\[data-session-theme\]/,
        'the sidebar row box carries selection; a rule that paints it by theme '
        + 'is the collision this change removes');
    assert.doesNotMatch(live, /\.running-session-row\[data-session-theme\]/,
        'and the same for the home card, or the collision has only moved');
});

test('no edge treatment of any kind survives here', () => {
    const live = liveTintCss();
    assert.doesNotMatch(live, /box-shadow/,
        'a ring and a rail are both edges, and an edge is the channel this '
        + 'change is giving back to selection');
    assert.doesNotMatch(live, /background-image/,
        'the wash was a row BACKGROUND, which is selection is other channel');
});

test('the swatch is the carrier, and it is locatable and theme-shaped', () => {
    const live = liveTintCss();
    assert.match(live, /\.session-theme-swatch\s*\{/,
        'the cue has to be somewhere, or this was a deletion');
    assert.match(live, /background-color:\s*var\(--session-theme-accent\)/,
        'the fill is the SESSION theme colour, which is the whole fact');
    assert.match(live, /border:\s*1px solid var\(--color-fg-subtle\)/,
        'the hairline is what makes a low-contrast accent visible at all - see '
        + 'the 529-pair sweep above, where the fill alone fails 139 pairs');
    assert.match(live, /border-radius:\s*var\(--radius-sm\)/,
        'the theme own radius token, so terminal / gameboy / legacy_apple get a '
        + 'square chip rather than a rounded one fighting their palette');
    assert.match(live, /flex-shrink:\s*0/,
        'the row is a flex line with an ellipsizing name; a shrinkable swatch '
        + 'would be squeezed to nothing by a long session name');
});

test('the stylesheet and the module are both still loaded, in a usable order', () => {
    const html = fs.readFileSync(path.join(ROOT, 'client', 'index.html'), 'utf8');
    assert.ok(html.indexOf('session-theme-tint.css') > -1,
        'session-theme-tint.css is not linked at all');
    const tint = html.indexOf('<script src="/static/js/session-theme-tint.js"></script>');
    const bundle = html.indexOf('<script type="module" src="/static/dist/app.js"></script>');
    assert.ok(tint > -1 && bundle > -1 && tint < bundle,
        'the compiled home card calls window.SessionThemeTint');
});

test('the focus ring is no longer overridden away on a themed row', () => {
    const density = fs.readFileSync(
        path.join(ROOT, 'client', 'css', 'session-sidebar-density.css'), 'utf8');
    assert.match(density, /:focus-visible\s*\{[^}]*box-shadow/,
        'the focus ring is still a box-shadow, so this file must keep away from '
        + 'that property on the row');
    assert.doesNotMatch(liveTintCss(), /box-shadow/);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the home card carries both halves, and the sidebar row carries NEITHER', () => {
    // the legacy twin
    const sidebar = ['row-plan.ts', 'SessionRow.svelte', 'row-chips.ts']
        .map((f) => fs.readFileSync(path.join(ROOT, 'web', 'src', 'lib', 'sidebar-shell', f), 'utf8')).join('\n');
    assert.ok(sidebar.includes('data-rename-state'), 'setup: the row sources were read');
    assert.doesNotMatch(sidebar, /SessionThemeTint|data-session-theme/,
        'the sidebar row must not reach for the theme cue at all - both halves went together');

    const host = fs.readFileSync(path.join(
        ROOT, 'web', 'src', 'lib', 'launchpad', 'running-host.ts'), 'utf8');
    assert.match(host, /SessionThemeTint/,
        'the home card must read the shared theme module, not a copy of it');
    assert.match(host, /colorsFor/, 'and it must read its DATA half');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
