
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

/**
 * Read one file from the repo root.
 * @param {...string} parts  Path segments below the repo root.
 * @returns {string} File contents.
 */
function read(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', ...parts), 'utf8');
}

function rules(css) {
    const clean = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/@media[^{]*\{/g, '');
    const out = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(clean)) !== null) out.push([m[1].trim(), m[2]]);
    return out;
}

const SHARED = new Set(['.modal-close', '.modal-close:hover']);

function offenders(list) {
    const bad = [];
    for (const [selector, body] of list) {
        if (SHARED.has(selector)) continue;
        for (const decl of body.split(';')) {
            const d = decl.trim();
            if (!d) continue;
            if (/--color-|#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/.test(d)) bad.push(`${selector}: ${d}`);
        }
    }
    return bad;
}

const styles = read('client', 'css', 'styles.css');
const start = styles.indexOf('/* Slash Commands Modal');
const end = styles.indexOf('/* Folder picker modal */');
const popupBlock = styles.slice(start, end);
const mobile = styles.slice(styles.indexOf('/* Mobile adjustments */'));
const mobilePopup = rules(mobile.slice(0, mobile.indexOf('.folder-picker-list')));
const chipsCss = read('client', 'css', 'slash-command-chips.css');
const modalJs = read('client', 'js', 'slash-commands.js');
const panel = read('web', 'src', 'lib', 'slash-favorites', 'FavoriteChips.svelte');
const panelStyle = panel.slice(panel.indexOf('<style>'), panel.indexOf('</style>'));
const model = read('web', 'src', 'lib', 'slash-favorites', 'favorites-model.ts');
const indexHtml = read('client', 'index.html');

test('the popup block in styles.css is found at all', () => {
    assert.ok(start >= 0 && end > start, 'the slash popup block moved; this test would check nothing');
    assert.ok(rules(popupBlock).length > 10, 'too few rules found; the parser is looking at nothing');
});

test('no popup rule in styles.css reads a session colour or a literal', () => {
    assert.deepEqual(offenders(rules(popupBlock)), []);
    assert.deepEqual(offenders(mobilePopup), []);
});

test('the popup uses the --oc palette, not nothing', () => {
    const tokens = popupBlock.match(/var\(--oc-[a-z-]+\)/g) || [];
    assert.ok(tokens.length >= 20, `only ${tokens.length} --oc tokens; the restyle is missing`);
});

test('the chip stylesheet reads no session colour or literal', () => {
    assert.deepEqual(offenders(rules(chipsCss)), []);
});

test('the panel wears the shared popup-focus look', () => {
    assert.match(modalJs, /class="modal-content slash-commands-modal-content popup-focus"/);
    assert.ok(indexHtml.indexOf('/static/css/popup-focus.css') > indexHtml.indexOf('/static/css/slash-command-chips.css'),
        'popup-focus.css must load after the chip styles so it wins at equal specificity');
});

test('the popup frame is not re-declared over popup-focus', () => {
    const panelRule = rules(popupBlock).find(([s]) => s === '.slash-commands-modal-content');
    assert.ok(panelRule, 'no .slash-commands-modal-content rule');
    assert.ok(!/(^|;)\s*(border|background|box-shadow)\s*:/.test(panelRule[1]),
        'popup-focus owns the border, ground and shadow');
});

test('no scale or glow on hover: the neon language is gone', () => {
    assert.ok(!/scale\(0\.95\)|translateX\(4px\)|accent-glow/.test(popupBlock));
});

test('the favorites panel styles itself from --oc tokens only', () => {
    assert.ok(panelStyle.length > 100, 'no <style> block found');
    assert.deepEqual(offenders(rules(panelStyle.replace('<style>', ''))), []);
});

test('a favorite colour paints from the token it names, never a hex', () => {
    assert.match(model, /return `var\(--oc-\$\{color\}\)`;/);
    assert.ok(!/#[0-9a-fA-F]{6}\b/.test(model), 'no hex value may live in the model');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
