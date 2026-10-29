import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const noComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');

let passes = 0;
let failures = 0;
const queue = [];
const test = (name, fn) => queue.push([name, fn]);

function ruleBody(css, selector) {
    const re = new RegExp(`(^|\\n|\\})\\s*${selector.replace(/[.[\]()]/g, '\\$&')}\\s*\\{([^}]*)\\}`);
    const m = css.match(re);
    return m ? m[2] : null;
}

function svelteStyle(rel) {
    const src = read(rel);
    const m = src.match(/<style[^>]*>([\s\S]*?)<\/style>/);
    assert.ok(m, `${rel} has no <style> block`);
    return noComments(m[1]);
}

function styleSources(dir) {
    const out = [];
    for (const entry of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
        const rel = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            if (entry.name === 'node_modules') continue;
            out.push(...styleSources(rel));
        } else if (/\.(css|svelte)$/.test(entry.name)) {
            out.push(rel);
        }
    }
    return out;
}

const SHARED = 'client/css/popup-focus.css';
const LOOK = /(^|\n)\s*(background|background-color|border|box-shadow)\s*:/;


test('the shared file registers one angle and declares one keyframes', () => {
    const css = noComments(read(SHARED));
    assert.equal((css.match(/@property\s+--pf-angle\b/g) || []).length, 1);
    assert.equal((css.match(/@keyframes\s+popup-focus-orbit\b/g) || []).length, 1);
    assert.equal((css.match(/@keyframes\s+/g) || []).length, 2, 'the registered-angle lap and the compositor turn, nothing else');
    const body = ruleBody(css, '.popup-focus');
    assert.ok(body, 'expected the .popup-focus rule');
    assert.match(body, /animation:\s*popup-focus-orbit\s+6s\s+linear\s+infinite/);
    assert.match(body, /conic-gradient\(\s*from var\(--pf-angle\)/);
    assert.match(body, /border:\s*1px solid transparent/);
});

test('no other stylesheet or component redraws the look or its motion', () => {
    const sources = [...styleSources('client/css'), ...styleSources('web/src')]
        .filter((rel) => rel !== SHARED);
    assert.ok(sources.length > 50, `population check: expected many style sources, got ${sources.length}`);
    const offenders = [];
    for (const rel of sources) {
        const css = noComments(read(rel));
        if (/--pf-angle|popup-focus-orbit|--srm-angle|srm-shimmer/.test(css)) offenders.push(rel);
    }
    assert.deepEqual(offenders, [], 'the angle and its keyframes live only in popup-focus.css');
});

test('reduced motion stops the lap and shows no sheen at all', () => {
    const css = noComments(read(SHARED));
    const i = css.indexOf('@media (prefers-reduced-motion: reduce)');
    assert.ok(i >= 0, 'expected a reduced-motion block');
    const block = css.slice(i);
    const body = ruleBody(block, '.popup-focus');
    assert.ok(body, 'expected .popup-focus inside the reduced-motion block');
    assert.match(body, /animation:\s*none/);
    assert.match(body, /--pf-sheen:\s*transparent/, 'a parked sheen is a bright stub at 0deg; it must be cleared');
});


test('the shared file is the last stylesheet the page links', () => {
    const html = read('client/index.html');
    const links = [...html.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map((m) => m[1]);
    assert.ok(links.length > 20, `population check: got ${links.length} stylesheet links`);
    assert.equal(links[links.length - 1], '/static/css/popup-focus.css');
    assert.equal(links.filter((h) => h.endsWith('/popup-focus.css')).length, 1);
});


const LEGACY = [
    ['client/js/header-menu.js', /panel\.className = 'header-menu-panel popup-focus'/,
        'client/css/header-menu.css', '.header-menu-panel'],
    ['client/js/fab-menu.js', /menuEl\.className = 'fab-menu popup-focus '/,
        'client/css/terminal-tools.css', '.fab-menu'],
    ['client/js/session-theme-menu.js', /pickerEl\.className = 'cloude-session-theme popup-focus'/,
        'client/css/terminal-tools.css', '.cloude-session-theme'],
    ['client/js/session-sidebar-group-actions.js', /menu\.className = 'session-sidebar-group-menu popup-focus'/,
        'client/css/session-sidebar-groups.css', '.session-sidebar-group-menu'],
];

for (const [js, pattern, cssFile, selector] of LEGACY) {
    test(`legacy ${selector} wears the shared class and draws no look of its own`, () => {
        assert.match(read(js), pattern, `${js} must add popup-focus to the panel it builds`);
        const body = ruleBody(noComments(read(cssFile)), selector);
        assert.ok(body, `expected the ${selector} rule in ${cssFile}`);
        assert.doesNotMatch(body, LOOK, `${selector} must not redeclare what popup-focus owns`);
    });
}

const COMPILED = [
    ['web/src/lib/drawer-tabs/CascadeMenu.svelte', 'acm-menu'],
    ['web/src/opscenter/engine/ComponentsPopover.svelte', 'oc-popover'],
    ['web/src/opscenter/cells/terminal-live/TerminalActions.svelte', 'cell-options'],
    ['web/src/lib/terminal-background/TerminalBackgroundButton.svelte', 'tbg-pop'],
    ['web/src/lib/file-drawer/FileDrawerHeader.svelte', 'fdh-menu'],
];

for (const [file, cls] of COMPILED) {
    test(`compiled .${cls} wears the shared class and draws no look of its own`, () => {
        const src = read(file);
        const anchored = new RegExp(`<AnchoredPopup[^>]*?class="${cls}"`).test(src);
        assert.ok(anchored || new RegExp(`class="${cls} popup-focus"`).test(src), `${file} must mark its panel`);
        const style = svelteStyle(file);
        const body = ruleBody(style, `.${cls}`) ?? ruleBody(style, `:global(.${cls})`);
        assert.ok(body, `expected the .${cls} rule in ${file}`);
        assert.doesNotMatch(body, LOOK, `.${cls} must not redeclare what popup-focus owns`);
    });
}

for (const [file, renders] of [
    ['web/src/opscenter/engine/CellMenu.svelte', 'PlacementMenuHost'],
    ['web/src/lib/zone-shell/PlacementMenuHost.svelte', 'CascadeMenu'],
    ['web/src/lib/item-menu/ItemMenuHost.svelte', 'CascadeMenu'],
    ['web/src/lib/sidebar-widgets/RailMenu.svelte', 'CascadeMenu'],
]) {
    test(`${file} draws through the shared cascade (which wears popup-focus)`, () => {
        assert.match(read(file), new RegExp(`<${renders}\\b`), `${file} must render ${renders}`);
        assert.doesNotMatch(noComments(read(file).replace(/^[\s\S]*?<\/script>/, '')),
            /class="[^"]*\b(oc-menu|acm-menu)\b/, `${file} must not build its own panel`);
    });
}


const FRAME = 'web/src/opscenter/shell/CellFrame.svelte';

test('every terminal frame carries a dimmed session-accent border', () => {
    const css = svelteStyle(FRAME);
    const body = ruleBody(css, '.oc-frame-terminal:not(.popup-focus)');
    assert.ok(body, 'expected the inactive terminal rule');
    const m = body.match(/border-color:\s*color-mix\(in srgb, var\(--oc-orange\) (\d+)%/);
    assert.ok(m, 'the inactive border must be the session accent, mixed down');
    const pct = Number(m[1]);
    assert.ok(pct > 0 && pct < 100, `dimmed means under full strength; got ${pct}%`);
    assert.doesNotMatch(body, /border-width|(^|\n)\s*border:|padding|width|height/,
        'colour only: nothing that can resize the pane');
});

test('the active terminal wears the shared look at full accent, same border width', () => {
    const src = read(FRAME);
    assert.match(src, /class:popup-focus=\{selected\}/, 'active is the selected terminal');
    assert.match(src, /const selected = \$derived\(\s*terminal && \(focused \|\| \(inputFocus\.owner === null && inputFocus\.selected === instance\)\)/,
        'selected is the input owner, or the last selected terminal while nothing owns input');
    const body = ruleBody(svelteStyle(FRAME), '.oc-frame-terminal.popup-focus');
    assert.ok(body, 'expected the active terminal rule');
    assert.match(body, /--pf-edge-top:\s*var\(--oc-orange\)/);
    assert.match(body, /--pf-edge-bottom:\s*var\(--oc-orange\)/);
    assert.match(body, /border-width:\s*var\(--oc-border\)/, 'the look must keep the frame border width');
    assert.doesNotMatch(body, /padding|(^|\n)\s*(width|height|min-|max-)/);
    const base = ruleBody(svelteStyle(FRAME), '.oc-frame');
    assert.doesNotMatch(base, LOOK, 'the unconditional frame rule would paint over the shared look');
    assert.ok(ruleBody(svelteStyle(FRAME), '.oc-frame:not(.popup-focus)'), 'the ground moves to the not-active rule');
});

test('the active terminal glows 5px in its accent, by shadow alone', () => {
    const body = ruleBody(svelteStyle(FRAME), '.oc-frame-terminal.popup-focus');
    assert.match(body, /--pf-glow:\s*color-mix\(in srgb, var\(--oc-orange\)/);
    assert.match(body, /box-shadow:\s*0 0 5px var\(--pf-glow\), inset 0 0 5px var\(--pf-glow\)/);
});

test('the selected frame turns its sheen on the compositor and the bare one keeps an overlay ring', () => {
    const src = read(FRAME);
    assert.match(src, /class:popup-focus-turn=\{selected\}/);
    assert.match(src, /class:popup-focus-ring=\{selected && meta\.chrome === 'bare'\}/);
    assert.match(src, /<span class="pf-sheen" aria-hidden="true"><\/span>/);
    const shared = noComments(read(SHARED));
    const keys = (shared.match(/@keyframes\s+popup-focus-turn\s*\{([\s\S]*?\})\s*\}/) || [])[1];
    assert.ok(keys, 'expected @keyframes popup-focus-turn');
    assert.match(keys, /transform:\s*rotate\(0deg\)/);
    assert.match(keys, /transform:\s*rotate\(360deg\)/);
    assert.doesNotMatch(keys, /--pf-angle|background|mask|width|height/, 'only transform may animate (issue #1809)');
    const turn = ruleBody(shared, '.popup-focus.popup-focus-turn');
    assert.match(turn, /animation:\s*none/, 'the frame itself no longer animates the registered angle');
    assert.doesNotMatch(turn, /conic-gradient/, 'the frame border is static');
    const host = ruleBody(shared, '.popup-focus-turn > .pf-sheen');
    assert.match(host, /position:\s*absolute/);
    assert.match(host, /pointer-events:\s*none/);
    assert.match(host, /mask-composite:\s*exclude/, 'a static mask clips the sheen to the 1px band');
    assert.doesNotMatch(host, /animation/, 'the host never animates, only its ::before');
    const turner = ruleBody(shared, '.popup-focus-turn > .pf-sheen::before');
    assert.match(turner, /animation:\s*popup-focus-turn\s+6s\s+linear\s+infinite/);
    assert.match(turner, /will-change:\s*transform/);
    assert.match(turner, /conic-gradient\(\s*from 0deg/);
    assert.match(shared, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.popup-focus-turn > \.pf-sheen::before \{\s*animation: none;/,
        'reduced motion stops the turning sheen as well');
    const base = ruleBody(shared, '.popup-focus.popup-focus-turn.popup-focus-ring');
    assert.match(base, /border:\s*0/, 'the bare frame keeps no border: its rectangle is the session size');
});

test('a terminal never stacks the old focus ring under the shared look', () => {
    const css = svelteStyle(FRAME);
    const ring = [...css.matchAll(/([^{}]*)::before\s*\{/g)].map((m) => m[1].trim())
        .filter((sel) => sel.includes('[data-oc-focus]'));
    assert.ok(ring.length >= 1, 'population check: the non-terminal ring still exists');
    for (const sel of ring) assert.match(sel, /:not\(\.oc-frame-terminal\)/, `${sel} must exclude terminals`);
});

for (const [name, fn] of queue) {
    try { await fn(); console.log(`ok - ${name}`); passes++; }
    catch (err) { console.log(`NOT OK - ${name}`); console.error(err); failures++; }
}
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
