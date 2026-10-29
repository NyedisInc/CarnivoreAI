
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

function css(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'css', name), 'utf8');
}

function js(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

/**
 * Strip `/* ... *\/` comments so prose cannot satisfy an assertion meant
 * for a declaration.
 * @param {string} sheet  Full stylesheet text.
 * @returns {string} The stylesheet with comments removed.
 */
function stripCssComments(sheet) {
    return sheet.replace(/\/\*[\s\S]*?\*\//g, '');
}

function ruleBody(sheet, selector) {
    const re = new RegExp(
        `(?:^|\\n)\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`
    );
    const m = sheet.match(re);
    assert.ok(m, `expected a rule for selector "${selector}"`);
    return m[1];
}

const html = fs.readFileSync(path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
const drawer = stripCssComments(css('config-drawer.css'));
const editorCss = stripCssComments(css('config-editor.css'));
const iosChrome = stripCssComments(css('ios-chrome.css'));
const panelJs = js('config-editor-panel.js');
const familiesJs = js('module-families.js');
const carnivoreCss = stripCssComments(css('terminal-carnivore.css'));


test('the picker box hugs the right edge and runs the full height', () => {
    const overlay = ruleBody(drawer, '.config-editor-picker-overlay');
    assert.match(overlay, /justify-content:\s*flex-end/, '.modal-overlay centres its child; the drawer must not be centred');
    assert.match(overlay, /align-items:\s*stretch/, 'full height, not vertically centred');

    const box = ruleBody(drawer, '.config-editor-picker-content');
    assert.match(box, /width:\s*var\(--config-drawer-w\)/, 'one token for width and dock offset');
    assert.match(box, /border-left:\s*1px solid/, 'a hairline on the edge facing the app');
});

test('the drawer pairs vh with dvh, in that order', () => {
    const box = ruleBody(drawer, '.config-editor-picker-content');
    const vh = box.indexOf('height: 100vh');
    const dvh = box.indexOf('height: 100dvh');
    assert.ok(vh !== -1 && dvh !== -1, 'both declarations must be present');
    assert.ok(vh < dvh, 'vh is the fallback and must come first, or it wins everywhere');
});

test('no pills or ovals - the drawer is square', () => {
    const box = ruleBody(drawer, '.config-editor-picker-content');
    assert.match(box, /border-radius:\s*0/, 'a drawer is part of the frame, not a floating card');
    assert.doesNotMatch(box, /border-radius:\s*var\(--radius-full\)/);
    assert.doesNotMatch(drawer, /border-radius:\s*999px/);
});

test('the old centred-dialog geometry is gone from config-editor.css', () => {
    assert.doesNotMatch(
        editorCss,
        /\.config-editor-picker-content\s*\{/,
        'config-drawer.css owns the box now - config-editor.css owns the contents');
});

test('the drawer takes the safe-area insets as a full-height panel', () => {
    assert.doesNotMatch(iosChrome, /\.config-editor-panel\b/, 'stale class name must not come back');
    assert.match(
        iosChrome,
        /\.session-sidebar-panel,\s*\n\s*\.config-editor-picker-content \{[^}]*safe-area-inset-top/,
        'the drawer is a full-height slide-over and owns both insets');
});


test('the pin module is deleted and no longer loaded', () => {
    assert.equal(
        fs.existsSync(path.join(__dirname, '..', 'client', 'js', 'config-drawer-pin.js')), false,
        'client/js/config-drawer-pin.js must not come back');
    assert.doesNotMatch(familiesJs, /config-drawer-pin/, 'the lazy family must not ask for it');
    assert.doesNotMatch(html, /config-drawer-pin/, 'no pin button and no pin script in the page');
});

test('the drawer never asks a pin anything', () => {
    assert.doesNotMatch(panelJs, /ConfigDrawerPin|isEffectivelyPinned|shouldDismissOnOutsideClick/);
});

test('no stylesheet keeps a pin or dock rule', () => {
    for (const [name, sheet] of [['config-drawer.css', drawer], ['config-editor.css', editorCss],
        ['terminal-carnivore.css', carnivoreCss]]) {
        assert.doesNotMatch(sheet, /config-drawer-pin|config-drawer-docked/, `${name} still styles the pin`);
    }
});

test('an outside click and Escape both dismiss; Escape asks the header first', () => {
    assert.match(panelJs, /if \(e\.target === this\.overlay\) this\.close\(\);/,
        'the backdrop is a dismissal, with no pin to ask');
    assert.match(panelJs, /onEscape: \(\) => this\._escape\(\)/);
    const escStart = panelJs.indexOf('async _escape() {');
    assert.ok(escStart !== -1, '_escape must exist');
    const escBody = panelJs.slice(escStart, panelJs.indexOf('\n    }', escStart));
    assert.match(escBody, /this\._header && this\._header\.escape\(\)\) return;\n\s*await this\.close\(\);/,
        'an open options menu or a typed query takes Escape before the drawer closes');
});


test('the drawer stylesheets are loaded, box after contents', () => {
    const drawerCssAt = html.indexOf('config-drawer.css');
    const editorCssAt = html.indexOf('config-editor.css');
    assert.ok(drawerCssAt !== -1, 'config-drawer.css must be linked');
    assert.ok(editorCssAt !== -1 && editorCssAt < drawerCssAt, 'the box overrides the contents sheet');
});

test('the header is an empty mount container, with no title', () => {
    assert.match(html, /<div class="config-editor-header" id="config-editor-header"><\/div>/,
        'the compiled header owns this container, so it carries no markup');
    assert.doesNotMatch(html, /config-editor-title|>file editor</, 'the "file editor" title is gone');
    assert.match(panelJs, /web\.fileDrawer\.mountHeader\(/, 'the drawer mounts the compiled header');
});

test('the filter and row modules load before the drawer', () => {
    const at = (name) => familiesJs.indexOf(`/static/js/${name}`);
    for (const name of ['config-editor-filter.js', 'config-editor-rows.js']) {
        assert.ok(at(name) !== -1, `${name} must be in the family`);
        assert.ok(at(name) < at('config-editor-panel.js'), `${name} must load before the panel`);
    }
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
