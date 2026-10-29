
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

const modalCss = stripCssComments(css('config-editor-modal.css'));
const stackCss = stripCssComments(css('modal-stack.css'));
const modalJs = js('config-editor-modal.js');
const panelJs = js('config-editor-panel.js');
const stackJs = js('modal-stack.js');


test('the editor box fills the viewport', () => {
    const body = ruleBody(modalCss, '.config-editor-modal-content');
    assert.match(body, /width:\s*100%/, 'full width');
    assert.match(body, /max-width:\s*none/, 'the old 900px cap must be lifted, not just overridden');
    assert.doesNotMatch(body, /max-width:\s*900px/);
    assert.doesNotMatch(body, /height:\s*min\(85/, 'the 85dvh card height must be gone');
});

test('nothing narrows the editor on a phone', () => {
    for (const m of modalCss.matchAll(/@media[^{]*\{([\s\S]*?)\n\}/g)) {
        assert.doesNotMatch(
            m[1], /\.config-editor-modal-content\s*\{/,
            'a media query must not resize the full-screen editor box');
    }
});

test('the height pairs vh with dvh, in that order', () => {
    const body = ruleBody(modalCss, '.config-editor-modal-content');
    const vh = body.indexOf('height: 100vh');
    const dvh = body.indexOf('height: 100dvh');
    assert.ok(vh !== -1 && dvh !== -1, 'both declarations must be present');
    assert.ok(vh < dvh, 'vh is the fallback and must come first, or it wins everywhere');
});

test('a full-screen surface draws no edge - flat, square, no pills', () => {
    const body = ruleBody(modalCss, '.config-editor-modal-content');
    assert.match(body, /border:\s*none/, 'there is no edge to outline');
    assert.match(body, /border-radius:\s*0/, 'square, matching the flattened settings screen');
});

test('the full-screen treatment is scoped to its own overlay class', () => {
    assert.match(
        modalJs, /className = 'modal-overlay config-editor-modal-overlay'/,
        'the editor overlay needs its own hook');
    assert.match(ruleBody(modalCss, '.config-editor-modal-overlay'), /padding:\s*0/);
});


test('back to files is shown at every width now', () => {
    const body = ruleBody(modalCss, '.config-editor-modal-back');
    assert.match(body, /display:\s*flex/, 'not display:none plus a phone-only rescue');
    assert.match(body, /width:\s*fit-content/, 'on its own line, sized to its own label');
    assert.doesNotMatch(
        modalCss,
        /@media \(max-width: 700px\) \{[^}]*\.config-editor-modal-back/,
        'the breakpoint that hid it on desktop must be gone - the drawer is covered there too now');
    assert.match(body, /width:\s*auto/, 'the bare button reset must be answered');
    assert.match(body, /height:\s*auto/, 'and answered for BOTH properties');
});

test('back is still only rendered when a picker is actually beneath', () => {
    assert.match(
        modalJs, /const stacked = window\.ModalStack\.depth\(\) > 0;/,
        'with nothing behind it, back is a second close button');
    assert.match(modalJs, /const backBtn = stacked/);
});


test('CodeMirror is still the editing surface', () => {
    assert.match(
        modalJs, /window\.CodeMirrorBundle\.createEditor\(/,
        'vendored CodeMirror, never a CDN load - the CSP is script-src self');
    assert.match(modalJs, /createEditor\(\s*\n\s*host,\s*\n\s*f\.originalContent,\s*\n\s*f\.path,/);
});

test('save still reports the .bak backup', () => {
    assert.match(
        modalJs,
        /result\.backed_up \? 'saved \(previous version backed up to \.bak\)' : 'saved'/,
        'the user is told the previous version survived');
    assert.match(modalJs, /window\.API\.writeConfigFile\(\{/);
});

test('the executable and sensitive write confirms both survive', () => {
    assert.match(modalJs, /acknowledge_executable: acknowledgeExecutable/);
    assert.match(modalJs, /acknowledge_sensitive: acknowledgeSensitive/);
    assert.match(modalJs, /'save executable file\?'/);
    assert.match(modalJs, /'save credentials file\?'/);
});

test('every dismissal gesture goes through the unsaved-changes guard', () => {
    for (const wiring of [
        "querySelector('#config-editor-modal-close').addEventListener('click', () => closeGuarded())",
        "querySelector('#config-editor-modal-back')\n                .addEventListener('click', () => closeGuarded())",
        "getElementById('config-editor-cancel').addEventListener('click', () => closeGuarded())",
        "onEscape: () => closeGuarded()",
        "overlayEl.addEventListener('click', (e) => { if (e.target === overlayEl) closeGuarded(); })",
    ]) {
        assert.ok(modalJs.includes(wiring), `missing guarded wiring: ${wiring}`);
    }
    assert.match(
        modalJs, /async function closeGuarded\(\) \{\n\s*if \(!\(await confirmDiscardIfDirty\(\)\)\) return;/,
        'the guard must come before the close, not after');
    assert.match(modalJs, /'discard unsaved changes\?'/);
});

test('the picker refuses to close over an unsaved editor too', () => {
    assert.match(panelJs, /const modal = window\.ConfigEditorModal;\n\s*if \(modal && !modal\.isInPlace\(\)\) \{\n\s*if \(modal\.isDirty\(\) && !\(await modal\.confirmDiscardIfDirty\(\)\)\) return;/);
});

test('the in-terminal editor guards every dismissal as well', () => {
    assert.ok(modalJs.includes("if (e.key !== 'Escape') return;"), 'in-place Escape is handled');
    assert.match(modalJs, /e\.stopPropagation\(\);\n\s*closeGuarded\(\);/,
        'and goes through the unsaved-changes guard');
});

test('Escape still closes only the top layer, and focus is restored', () => {
    assert.match(stackJs, /const top = stack\[stack\.length - 1\];/, 'one entry, the top one');
    assert.match(stackJs, /if \(!topIsOutermost\(\)\) return;/,
        'an unregistered confirm dialog above the stack keeps its own Escape');
    assert.match(stackJs, /previousFocus/, 'focus returns to the row that opened the editor');
    assert.match(
        modalJs, /window\.ModalStack\.pop\(overlayEl\);\n\s*if \(overlayEl\.parentNode\)/,
        'pop BEFORE detaching or there is nothing sensible to focus');
});

test('background scroll stays locked while anything is stacked', () => {
    assert.match(stackJs, /BODY_LOCK_CLASS, stack\.length > 0/);
    assert.match(
        stackCss,
        /body\.modal-stack-locked,\s*\n\s*html:has\(body\.modal-stack-locked\) \{[^}]*overflow:\s*hidden/);
});

test('the covered surface underneath is inert and off screen on a phone', () => {
    assert.match(stackJs, /setAttribute\('inert', ''\)/, 'covered means not tabbable');
    assert.match(
        stackCss,
        /@media \(max-width: 700px\) \{\s*\n\s*\.modal-stack--covered \{\s*\n\s*display:\s*none/,
        'one thing at a time on a phone');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
