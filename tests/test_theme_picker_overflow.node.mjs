// (client/css/terminal-tools.css, `.cloude-session-theme__item`).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

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
 * Read a CSS file from the client.
 * @param {string} name  File name under client/css.
 * @returns {string} File contents.
 */
function css(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'css', name), 'utf8');
}

function ruleBody(source, selector) {
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].trim() !== selector + ' {') continue;
        const out = [];
        for (let j = i + 1; j < lines.length && lines[j].trim() !== '}'; j++) {
            out.push(lines[j]);
        }
        return out.join('\n');
    }
    throw new Error(`selector not found: ${selector}`);
}

function simulateRowWidth(label, containerMax, canBreakAnywhere) {
    const longestUnbrokenRun = canBreakAnywhere
        ? 1
        : Math.max(...label.split(/\s+/).map((w) => w.length));
    const contentWidth = Math.min(longestUnbrokenRun, containerMax === Infinity ? longestUnbrokenRun : longestUnbrokenRun);
    const overflowsBy = Math.max(0, longestUnbrokenRun - containerMax);
    return { contentWidth, overflowsBy };
}

// ---------------------------------------------------------------------
// The CSS contract - the actual regression guard
// ---------------------------------------------------------------------

test('.cloude-session-theme__item allows a break anywhere in the label', () => {
    const body = ruleBody(css('terminal-tools.css'), '.cloude-session-theme__item');
    assert.match(body, /overflow-wrap:\s*anywhere\s*;/,
        '.cloude-session-theme__item must declare overflow-wrap: anywhere');
});

test('.cloude-session-theme__item opts out of the flex-item auto-minimum', () => {
    const body = ruleBody(css('terminal-tools.css'), '.cloude-session-theme__item');
    assert.match(body, /min-width:\s*0\s*;/,
        '.cloude-session-theme__item must declare min-width: 0');
});

test('.cloude-session-theme__item does not force a single line', () => {
    const body = ruleBody(css('terminal-tools.css'), '.cloude-session-theme__item');
    assert.doesNotMatch(body, /white-space:\s*nowrap/,
        '.cloude-session-theme__item must not force nowrap');
});

test('the tap target floor survives the wrap fix', () => {
    const body = ruleBody(css('terminal-tools.css'), '.cloude-session-theme__item');
    assert.match(body, /min-height:\s*44px\s*;/);
    assert.match(body, /height:\s*auto\s*;/);
});

test('the list keeps its vertical scroller (unrelated axis, must survive)', () => {
    const body = ruleBody(css('terminal-tools.css'), '.cloude-session-theme__list');
    assert.match(body, /overflow-y:\s*auto\s*;/,
        '.cloude-session-theme__list must still scroll vertically for a large theme library');
});

test('the picker container keeps its viewport clamp', () => {
    const body = ruleBody(css('terminal-tools.css'), '.cloude-session-theme');
    assert.match(body, /max-width:\s*min\(280px,\s*calc\(100vw - 16px\)\)\s*;/,
        '.cloude-session-theme must stay clamped into the viewport');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('an unbreakable label overflows a clamped row without the fix', () => {
    const label = 'supercalifragilisticexpialidociousthemepack2000';
    const containerMax = 40;
    const before = simulateRowWidth(label, containerMax,  false);
    assert.ok(before.overflowsBy > 0,
        `expected overflow without the fix, got ${JSON.stringify(before)}`);
});

test('the same label fits once a break-anywhere opportunity exists', () => {
    const label = 'supercalifragilisticexpialidociousthemepack2000';
    const containerMax = 40;
    const after = simulateRowWidth(label, containerMax,  true);
    assert.equal(after.overflowsBy, 0,
        `expected zero overflow with the fix, got ${JSON.stringify(after)}`);
});

test('an id-fallback name (underscore-joined, no spaces) is the same failure class', () => {
    const idFallback = 'a_theme_id_with_no_spaces_at_all_whatsoever';
    const containerMax = 40;
    const before = simulateRowWidth(idFallback, containerMax, false);
    const after = simulateRowWidth(idFallback, containerMax, true);
    assert.ok(before.overflowsBy > 0, 'id-fallback form must overflow pre-fix');
    assert.equal(after.overflowsBy, 0, 'id-fallback form must fit post-fix');
});

test('all real bundled theme names/ids fit even at the pre-fix rule (sanity)', () => {
    const themesDir = path.join(__dirname, '..', 'client', 'css', 'themes');
    const dirs = fs.readdirSync(themesDir).filter((d) =>
        fs.statSync(path.join(themesDir, d)).isDirectory()
        && fs.existsSync(path.join(themesDir, d, 'theme.json')));
    assert.ok(dirs.length > 0, 'expected at least one bundled theme, found none');
    const containerMax = 40;
    for (const d of dirs) {
        const manifest = JSON.parse(
            fs.readFileSync(path.join(themesDir, d, 'theme.json'), 'utf8'));
        const label = (manifest.name || manifest.id).toLowerCase();
        const result = simulateRowWidth(label, containerMax, false);
        assert.equal(result.overflowsBy, 0,
            `${d}: "${label}" unexpectedly overflows even the pre-fix rule`);
    }
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
