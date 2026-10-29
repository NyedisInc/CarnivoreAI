// The properties that matter:

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createEnvironment } from './mini-dom.mjs';
import CATALOG from '../client/js/i18n/catalog.en.js';
import { terminalKeyBarLabels } from '../client/js/labels/terminal-key-bar.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

/**
 * Read a file under client/.
 * @param {...string} parts  Path segments under client/.
 * @returns {string} File contents.
 */
function clientFile(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', ...parts), 'utf8');
}

function cssRules(css) {
    return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

const ENTRY_IDS = [
    'toolAttachImage',
    'toolPasteClipboard',
    'toolCopyOutput',
];

const EDITOR_IDS = ['headerSessionThemeBtn', 'headerDetachBtn', 'sessionMusicRow'];

function load() {
    const env = createEnvironment({});
    const calls = { copyOpen: 0, paste: 0, inputClick: 0 };

    const trigger = env.document.createElement('button');
    trigger.className = 'terminal-key-bar__key';
    trigger.setAttribute('data-key-bar-action', 'paste');
    env.document.body.appendChild(trigger);

    const input = env.document.createElement('input');
    input.setAttribute('id', 'cloude-image-attach-input');
    input.click = () => { calls.inputClick++; };
    env.document.body.appendChild(input);

    env.window.CopyOutput = { open: () => { calls.copyOpen++; } };
    env.window.ClipboardTools = { pasteFromClipboard: () => { calls.paste++; } };
    env.window.AnchorPopover = { place: () => ({ left: 0, top: 0 }) };

    const sandbox = {
        window: env.window,
        document: env.document,
        console: { log() {}, warn() {}, error() {} },
        setTimeout: (fn) => fn(),
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(clientFile('js', 'fab-menu.js'), sandbox);
    vm.runInContext(clientFile('js', 'terminal-tools-menu.js'), sandbox);

    const menu = env.window.TerminalToolsMenu;
    menu.wire({ _showStatusPill() {} }, input);
    menu.toggle(trigger);
    menu.close();
    return { env, menu, trigger, input, calls };
}

function row(env, id) {
    const found = env.document.body.children
        .filter((c) => c.className === 'fab-menu popup-focus terminal-tools-menu')
        .flatMap((m) => m.children)
        .find((r) => r.getAttribute('id') === id);
    assert.ok(found, `row ${id} is missing from the open menu`);
    return found;
}

function openIds(env) {
    return env.document.body.children
        .filter((c) => c.className === 'fab-menu popup-focus terminal-tools-menu')
        .flatMap((m) => m.children)
        .map((r) => r.getAttribute('id'));
}

// ---------------------------------------------------------------------
// The split
// ---------------------------------------------------------------------

test('the menu is closed on load and a tap on the key toggles it', () => {
    const { menu, trigger } = load();
    assert.equal(menu.isOpen(), false);
    menu.toggle(trigger);
    assert.equal(menu.isOpen(), true);
    assert.equal(trigger.getAttribute('aria-expanded'), 'true');
    menu.toggle(trigger);
    assert.equal(menu.isOpen(), false);
    assert.equal(trigger.getAttribute('aria-expanded'), 'false');
});

test('THE SPLIT: tools holds the three content rows and nothing else', () => {
    const { env, menu } = load();
    menu.open();
    assert.deepEqual(openIds(env), ENTRY_IDS);
});

test('THE SPLIT: session theme, detach and sound are NOT rows of the tools menu', () => {
    const { env, menu } = load();
    menu.open();
    const ids = openIds(env);
    for (const id of EDITOR_IDS) {
        assert.ok(!ids.includes(id), `${id} belongs to the header kebab`);
    }
    const src = clientFile('js', 'terminal-tools-menu.js');
    assert.ok(!src.includes('SessionThemeMenu'),
        'the tools menu must not reach into session theme at all');
    assert.ok(!src.includes('TerminalController.detachSession'),
        'the tools menu must not reach into detach at all');
    assert.ok(!Object.keys(menu.ICONS).includes('theme'));
    assert.ok(!Object.keys(menu.ICONS).includes('music'));
});

test('THE SPLIT: session theme and detach are built by the header kebab, not this menu', () => {
    const html = clientFile('index.html');
    assert.ok(!html.includes('id="sessionEditorBtn"'),
        'the old sliders-icon header button is deleted, not replaced');
    assert.ok(html.includes('/static/js/fab-menu.js'),
        'the shared plumbing must still load for this menu');
    assert.ok(html.indexOf('/static/js/fab-menu.js')
        < html.indexOf('/static/js/terminal-tools-menu.js'));
    assert.ok(!html.includes('aria-controls="sessionEditorMenu"'));
    assert.ok(clientFile('js', 'terminal.js').includes(
        "wire(this, this._chrome('fileInput'))"));
    assert.ok(!clientFile('js', 'terminal.js').includes('SessionEditorMenu'),
        'terminal.js must not wire a module that no longer exists');
});

test('NOTHING WAS LOST: each tools row calls the module that owns it', () => {
    const cases = [
        ['toolCopyOutput', 'copyOpen'],
        ['toolPasteClipboard', 'paste'],
        ['toolAttachImage', 'inputClick'],
    ];
    for (const [id, counter] of cases) {
        const { env, menu, calls } = load();
        menu.open();
        row(env, id).dispatchEvent('click');
        assert.equal(calls[counter], 1, `${id} did not reach its module`);
    }
});

test('THE ATTACH CAPABILITY SURVIVED: the row opens the real file input', () => {
    const { env, menu, calls } = load();
    menu.open();
    row(env, 'toolAttachImage').dispatchEvent('click');
    assert.equal(calls.inputClick, 1);
    const html = clientFile('index.html');
    assert.ok(html.includes('id="cloude-image-attach-input"'),
        'the hidden file input must still be mounted');
    // NO accept attribute since 2026-08-16: it steered the iOS picker at
    assert.ok(!/id="cloude-image-attach-input"[^>]*accept=/.test(html),
        'the picker must offer Files, not just Photos');
    assert.ok(clientFile('js', 'clipboard.js').includes('function wireFileInput'));
    const term = clientFile('js', 'terminal.js');
    assert.ok(term.includes('ClipboardTools.wireFileInput'));
    assert.ok(term.includes('_uploadAndInjectFile'),
        'the upload + path-injection flow must survive the resplit');
    assert.ok(clientFile('js', 'clipboard.js').includes('function uploadAndInject'),
        'the flow itself lives in clipboard.js, not in terminal.js');
});

test('picking a tool closes the menu, so it never sits over the terminal', () => {
    const { env, menu } = load();
    menu.open();
    row(env, 'toolCopyOutput').dispatchEvent('click');
    assert.equal(menu.isOpen(), false);
});

test('Escape closes, and a click outside closes', () => {
    const esc = load();
    esc.menu.open();
    esc.env.document.dispatchEvent('keydown', { key: 'Escape' });
    assert.equal(esc.menu.isOpen(), false);

    const out = load();
    out.menu.open();
    const elsewhere = out.env.document.createElement('div');
    out.env.document.body.appendChild(elsewhere);
    out.env.document.dispatchEvent('pointerdown', { target: elsewhere });
    assert.equal(out.menu.isOpen(), false);
});

test('close() and a second open() are both safe, and never stack two menus', () => {
    const { env, menu } = load();
    menu.close();
    menu.open();
    menu.open();
    const menus = env.document.body.children
        .filter((c) => c.className === 'fab-menu popup-focus terminal-tools-menu');
    assert.equal(menus.length, 1);
});

test('toggle() anchors to the tapped key, and a re-wire on a session swap keeps it working', () => {
    const { env, menu, trigger, calls } = load();
    menu.wire({ _showStatusPill() {} }, null);
    menu.wire({ _showStatusPill() {} }, null);
    menu.toggle(trigger);
    assert.equal(menu.isOpen(), true);
    assert.equal(calls.copyOpen, 0);
    const repainted = env.document.createElement('button');
    env.document.body.appendChild(repainted);
    menu.toggle(repainted);
    assert.equal(menu.isOpen(), false);
    assert.equal(trigger.getAttribute('aria-expanded'), 'false');
    menu.toggle(repainted);
    assert.equal(repainted.getAttribute('aria-expanded'), 'true');
});

test('THE TRAY KEY RUNS THE ONE PASTE IMPLEMENTATION, through the menu the floating button opened', () => {
    const env = createEnvironment({});
    const screen = env.document.createElement('div');
    screen.setAttribute('id', 'terminal-screen');
    env.document.body.appendChild(screen);
    const pasted = [];
    const wrapper = { name: 'the page terminal' };
    env.window.ClipboardTools = { pasteFromClipboard: (t) => { pasted.push(t); } };
    env.window.AnchorPopover = { place: () => ({ left: 0, top: 0 }) };
    env.window.CloudeLabels = { terminalKeyBarLabels };
    env.window.CloudeI18n = { t: (k) => (k in CATALOG ? CATALOG[k] : k) };
    const sandbox = {
        window: env.window,
        document: env.document,
        console: { log() {}, warn() {}, error() {} },
        setTimeout: (fn) => fn(),
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(clientFile('js', 'fab-menu.js'), sandbox);
    vm.runInContext(clientFile('js', 'terminal-tools-menu.js'), sandbox);
    vm.runInContext(clientFile('js', 'terminal-key-bar.js'), sandbox);
    env.window.TerminalToolsMenu.wire(wrapper, null);

    const key = env.document.body.querySelector('[data-key-bar-action="paste"]');
    assert.ok(key, 'the key bar must paint its clipboard key');
    assert.equal(key.getAttribute('aria-haspopup'), 'menu');
    key.dispatchEvent('click');
    assert.equal(env.window.TerminalToolsMenu.isOpen(), true,
        'the tray key must open the terminal tools menu');
    assert.deepEqual(openIds(env), ENTRY_IDS, 'all three rows, attach file first');
    assert.equal(pasted.length, 0, 'opening the menu reads no clipboard');
    row(env, 'toolPasteClipboard').dispatchEvent('click');
    assert.deepEqual(pasted, [wrapper],
        'the paste row runs the one implementation, into the wired terminal');
    const barSrc = clientFile('js', 'terminal-key-bar.js')
        .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    assert.ok(!barSrc.includes('pasteFromClipboard'),
        'the key bar must not carry a second paste path');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the top-right tool strip is gone from the markup and the tree', () => {
    const html = clientFile('index.html');
    for (const id of ['terminalTools', 'terminalToolsToggle', 'terminalCopyBtn',
        'sessionThemeBtn', 'sessionAudioBtn']) {
        assert.ok(!html.includes(`id="${id}"`), `index.html still mounts ${id}`);
    }
    assert.ok(!html.includes('terminal-tools-fold.js'),
        'index.html must not load the deleted fold module');
    assert.ok(!fs.existsSync(path.join(__dirname, '..', 'client', 'js',
        'terminal-tools-fold.js')), 'the fold module must be deleted');
    assert.ok(html.includes('/static/js/terminal-tools-menu.js'),
        'index.html must load the menu module');
});

test('clipboard.js no longer builds a second menu', () => {
    const src = clientFile('js', 'clipboard.js');
    assert.ok(!src.includes('cloude-attach-menu'),
        'the paperclip popup must be gone, not just unused');
    assert.ok(!src.includes('function openMenu'));
    assert.ok(src.includes('function pasteFromClipboard'),
        'the paste capability itself must survive');
});

test('the shared plumbing lives in fab-menu.js, not restated here', () => {
    const tools = clientFile('js', 'terminal-tools-menu.js');
    assert.ok(tools.includes('window.FabMenu.create('),
        'terminal-tools-menu.js must use the shared controller');
    assert.ok(!tools.includes("addEventListener('pointerdown'"),
        'terminal-tools-menu.js must not re-implement outside-click dismissal');
    assert.ok(!tools.includes("e.key === 'Escape'"),
        'terminal-tools-menu.js must not re-implement Escape dismissal');
    assert.ok(tools.split('\n').length < 500, 'terminal-tools-menu.js must stay small');
    assert.ok(clientFile('js', 'fab-menu.js').split('\n').length < 500);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('ICONS: every path declares stroke-width 1.5 in a 16x16 viewBox', () => {
    const { menu } = load();
    const headerSrc = clientFile('js', 'header-menu.js');
    const kebabIcons = ['headerSessionThemeBtn', 'headerDetachBtn'].map((id) => {
        const at = headerSrc.indexOf(`id = '${id}'`);
        const chunk = headerSrc.slice(at, headerSrc.indexOf('addEventListener', at));
        return [id, chunk.slice(chunk.indexOf('<svg'), chunk.lastIndexOf('</svg>'))];
    });
    const bodies = Object.entries(menu.ICONS).concat(kebabIcons);
    for (const [name, body] of bodies) {
        const strokedShapes = body.match(/<(path|rect|circle)\b[^>]*stroke="currentColor"[^>]*>/g) || [];
        assert.ok(strokedShapes.length, `${name} has no stroked shape`);
        for (const shape of strokedShapes) {
            assert.ok(/stroke-width="1\.5"/.test(shape),
                `${name} has a stroked shape without stroke-width 1.5: ${shape}`);
        }
    }
    const src = clientFile('js', 'fab-menu.js');
    assert.ok(src.includes("setAttribute('viewBox', '0 0 16 16')"));
    assert.ok(src.includes("setAttribute('width', '16')"));
    assert.ok(src.includes("setAttribute('height', '16')"));
});

test('THE FLOATING BUTTON IS GONE: no markup, no rule, no token', () => {
    const html = clientFile('index.html');
    assert.ok(!html.includes('id="terminalToolsBtn"'),
        'the round floating tools button must not be mounted');
    assert.ok(!html.includes('aria-controls="terminalToolsMenu"'));
    assert.ok(!clientFile('js', 'terminal-client-factory.js').includes('terminalToolsBtn'),
        'no page-chrome lookup may still reach for it');
    const sheets = fs.readdirSync(path.join(__dirname, '..', 'client', 'css'))
        .filter((f) => f.endsWith('.css'));
    assert.ok(sheets.length > 10, 'the stylesheet scan must actually read sheets');
    for (const f of sheets) {
        const rules = cssRules(clientFile('css', f));
        for (const gone of ['.fab-menu-btn', '.terminal-tools-fab', '#terminalToolsBtn']) {
            assert.ok(!rules.includes(gone), `${f} still styles ${gone}`);
        }
        assert.ok(!/--fab-[\w-]+\s*:/.test(rules), `${f} still declares a --fab-* token`);
        assert.ok(!/var\(--fab-/.test(rules), `${f} still reads a --fab-* token`);
    }
});

test('the two kebab session rows carry distinguishable glyphs, in the same set', () => {
    const src = clientFile('js', 'header-menu.js');
    const glyphs = {};
    for (const id of ['headerSessionThemeBtn', 'headerDetachBtn']) {
        const at = src.indexOf(`id = '${id}'`);
        assert.ok(at > 0, `${id} must be built`);
        const chunk = src.slice(at, at + 1200);
        assert.ok(chunk.includes('viewBox="0 0 16 16"'), `${id}: same viewBox as the set`);
        assert.ok(chunk.includes('width="16" height="16"'), `${id}: same rendered size`);
        const svg = chunk.slice(chunk.indexOf('<svg'), chunk.indexOf('</svg>'));
        const shapes = svg.match(/<(path|circle|rect)\b[^>]*>/g) || [];
        assert.ok(shapes.length >= 2, `${id}: the glyph must be drawn`);
        for (const shape of shapes) {
            assert.ok(/stroke-width="1\.5"/.test(shape) || /fill="currentColor"/.test(shape),
                `${id}: every shape carries its own stroke or fill: ${shape}`);
        }
        glyphs[id] = svg;
    }
    assert.notEqual(glyphs.headerSessionThemeBtn, glyphs.headerDetachBtn,
        'the two rows must be distinguishable at a glance');
});

test('GEOMETRY: the retired floating controls stay deleted', () => {
    const base = clientFile('css', 'styles.css');
    const ios = clientFile('css', 'ios-chrome.css');
    for (const gone of ['.dpad-float-button', '.slash-commands-btn']) {
        assert.ok(!cssRules(base).includes(gone),
            `${gone} must be deleted with the control it painted`);
        assert.ok(!cssRules(ios).includes(gone),
            `${gone} must not be left in the safe-area rule either`);
    }
    assert.ok(!/\.session-editor-fab/.test(cssRules(ios)),
        'no rail rule and no exclusion naming it: the class does not exist');
    assert.ok(!base.includes('.cloude-image-attach-button'),
        'the old hardcoded attach-button geometry must be gone');
});

test('GEOMETRY: the session editor left the header entirely, and the rail is gone', () => {
    const base = clientFile('css', 'styles.css');
    const tools = clientFile('css', 'terminal-tools.css');
    const ios = clientFile('css', 'ios-chrome.css');
    const html = clientFile('index.html');

    assert.ok(!html.includes('id="sessionEditorBtn"'),
        'the session editor button must be gone from the header entirely');

    assert.ok(!/\.session-editor-fab\s*\{/.test(cssRules(tools)),
        'the top-right rail rule must be removed, not merely overridden');
    assert.ok(!/\.session-editor-fab/.test(cssRules(ios)));
    assert.ok(!/--fab-top-edge\s*:/.test(cssRules(base)),
        'an orphan token is how a retired layout gets revived by accident');
    assert.ok(!/var\(--fab-top-edge\)/.test(
        cssRules(tools) + cssRules(ios) + cssRules(base)),
        'and nothing may still read it');

    assert.match(base,
        /\.header--home \{\s*\n\s*--home-header-flank-w: calc\(var\(--control-size\) \* 2 \+ 8px\);/);

    assert.match(base,
        /--header-h:\s*calc\(var\(--control-size\) \+ var\(--header-pad-y\) \* 2\s*\n?\s*\+ var\(--header-border\) \+ var\(--home-subheader-extra\)\);/);
    const headerRule = ruleOf(base, '.header');
    assert.match(headerRule, /padding:\s*var\(--header-pad-y\) var\(--header-pad-x\);/);
    assert.match(headerRule, /border-bottom:\s*var\(--header-border\) solid/);
    assert.match(ruleOf(base, '.btn-icon'),
        /width:\s*var\(--control-size\);\n\s*height:\s*var\(--control-size\);/);
    assert.match(ios,
        /padding-top:\s*calc\(var\(--header-pad-y\) \+ env\(safe-area-inset-top\)\);/);

    for (const [width, control] of [[1280, 36], [768, 44], [390, 40]]) {
        assert.ok(control >= 36, `${width}px control must stay a real target`);
    }
    assert.match(base, /@media \(max-width: 768px\) \{[\s\S]{0,400}?--control-size: 44px;/,
        'the touch breakpoint must still raise every header control to 44px');
});

test('CHANGE 1: the terminal tools menu is MOBILE ONLY', () => {
    const base = clientFile('css', 'styles.css');
    const tools = clientFile('css', 'terminal-tools.css');
    const gate = /@media \(min-width: 769px\) \{\s*\n\s*\.terminal-tools-menu \{\s*\n\s*display: none !important;/;
    assert.match(tools, gate,
        'the tools menu must be hidden above the breakpoint, with its key bar');

    assert.match(clientFile('css', 'terminal-key-bar.css'),
        /@media \(min-width: 769px\) \{\s*\n\s*#terminal-key-bar \{\s*\n\s*display: none;/,
        'the key bar must be touch-only at the same 769px line');

    for (const f of ['terminal-tools-menu.js', 'terminal.js', 'fab-menu.js']) {
        const src = clientFile('js', f).replace(/\/\*[\s\S]*?\*\//g, '')
            .replace(/^\s*\/\/.*$/gm, '');
        assert.ok(!/innerWidth|matchMedia/.test(src),
            `${f} must not gate the tools FAB in JS; the media query owns it`);
    }

    assert.ok(!/@media \(min-width: 769px\)[\s\S]*?session-editor/.test(cssRules(tools)));
    const headerMenuCss = clientFile('css', 'header-menu.css');
    assert.ok(headerMenuCss.includes('#headerSessionThemeBtn,\n#headerDetachBtn {'),
        'the session-row display gate must exist');
    assert.ok(!/@media\s*\(\s*(?:min|max)-width/.test(headerMenuCss),
        'header-menu.css must carry no width-based media query at all');
});

test('the top-right corner is empty, and no strip ever comes back', () => {
    const html = clientFile('index.html');
    const tools = clientFile('css', 'terminal-tools.css');
    assert.ok(!/\.terminal-tools\s*\{/.test(cssRules(tools)),
        'the top-right tool strip must not be reintroduced');
    const onRail = (cssRules(tools).match(/top:\s*var\(--fab-top-edge\)/g) || []).length;
    assert.equal(onRail, 0, 'nothing may sit on the retired top-right rail');
    assert.ok(!/--fab-top-slot-\d+\s*:/.test(cssRules(clientFile('css', 'styles.css'))),
        'the top rail is retired - do not build a row there');
    assert.ok(!html.includes('id="sessionEditorBtn"'));
});

test('NOTHING MOVED INSIDE #terminal, so the scroll guard cannot eat a tap', () => {
    const html = clientFile('index.html');
    assert.ok(/<div id="terminal"[^>]*><\/div>/.test(html),
        '#terminal must stay empty in the markup');
    const screenEnd = html.indexOf('<!-- Vendored xterm.js');
    assert.ok(screenEnd > 0);
    assert.ok(html.indexOf('id="cloude-image-attach-input"') > screenEnd,
        'the file input must sit outside #terminal-screen, not inside #terminal');
    assert.equal(depthOfElement(html, 'cloude-image-attach-input'), 0,
        'the file input must be a DIRECT child of <body>');

    const kebabSrc = clientFile('js', 'header-menu.js');
    assert.ok(!/getElementById\(['"]terminal['"]\)/.test(kebabSrc),
        'header-menu.js must not mount anything inside #terminal');
    assert.ok(/this\.controls\.appendChild\(theme\)/.test(kebabSrc)
        && /this\.controls\.appendChild\(detach\)/.test(kebabSrc),
        'both session rows must be appended to .controls, not to #terminal or body');
    const fab = clientFile('js', 'fab-menu.js');
    assert.ok(fab.includes('document.body.appendChild(menuEl)'));
    assert.ok(!fab.includes("getElementById('terminal')"));
    assert.ok(!clientFile('js', 'terminal-tools-menu.js').includes("getElementById('terminal')"),
        'terminal-tools-menu.js must not mount anything inside #terminal');
    assert.match(clientFile('css', 'styles.css'),
        /\.terminal-container \{[^}]*overscroll-behavior: contain;/s);
});

test('GEOMETRY: desktop leaves no hole in the bottom row', () => {
    const base = clientFile('css', 'styles.css');
    const tools = clientFile('css', 'terminal-tools.css');
    assert.match(clientFile('css', 'terminal-key-bar.css'),
        /@media \(min-width: 769px\) \{\s*\n\s*#terminal-key-bar \{\s*\n\s*display: none;/,
        'the key bar must be touch-only');
    assert.ok(!/\.session-editor-fab/.test(cssRules(tools)),
        'the editor is off the bottom row and off every rail');
    assert.match(tools,
        /@media \(min-width: 769px\) \{\s*\n\s*\.terminal-tools-menu \{/,
        'the menu must leave at the width its key bar does');
});

function depthOfElement(html, id) {
    const bodyAt = html.indexOf('<body');
    const target = html.indexOf(`id="${id}"`);
    assert.ok(bodyAt >= 0 && target > bodyAt, `${id} must appear inside <body>`);
    const from = html.indexOf('>', bodyAt) + 1;
    const tagStart = html.lastIndexOf('<', target);
    const region = html.slice(from, tagStart).replace(/<!--[\s\S]*?-->/g, '');

    const VOID = new Set(['input', 'br', 'hr', 'img', 'link', 'meta', 'source']);
    let depth = 0;
    for (const m of region.matchAll(/<(\/?)([a-zA-Z][\w-]*)\b([^>]*)>/g)) {
        const [, closing, name, attrs] = m;
        const tag = name.toLowerCase();
        if (VOID.has(tag) || attrs.trimEnd().endsWith('/')) continue;
        depth += closing ? -1 : 1;
        assert.ok(depth >= 0, `unbalanced markup before #${id}`);
    }
    return depth;
}

function ruleOf(css, sel) {
    const at = css.indexOf(sel + ' {');
    assert.ok(at > -1, `${sel} rule not found`);
    return css.slice(at, css.indexOf('}', at));
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the tools menu and the header kebab stay separate controls', () => {
    const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '');
    const menuSrc = stripComments(clientFile('js', 'terminal-tools-menu.js'));
    const kebabSrc = stripComments(clientFile('js', 'header-menu.js'));
    assert.ok(!clientFile('js', 'terminal.js').includes('SessionEditorMenu'),
        'terminal.js must not wire a module that no longer exists');
    assert.ok(!menuSrc.includes('header-menu-toggle'),
        'the tools menu must not drive the header kebab');
    assert.ok(!menuSrc.includes('header-menu-panel'));
    assert.ok(!kebabSrc.includes('terminalToolsBtn'),
        'the header kebab must not drive the tools menu');
    assert.ok(!kebabSrc.includes('terminalToolsMenu'));
    for (const id of ['homeBtn', 'detachSessionBtn', 'logoutBtn', 'settingsBtn',
        'configEditorBtn', 'audioToggleBtn']) {
        assert.ok(!ENTRY_IDS.includes(id), `${id} is claimed by both menus`);
        assert.ok(!EDITOR_IDS.includes(id), `${id} is claimed by both menus`);
        assert.ok(!menuSrc.includes(`'${id}'`), `the tools menu must not claim ${id}`);
    }
    for (const id of EDITOR_IDS) {
        assert.ok(!menuSrc.includes(`'${id}'`),
            `the tools menu must not claim ${id} - it belongs to the header kebab`);
    }
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
