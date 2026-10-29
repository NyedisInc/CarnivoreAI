//     button { width: var(--control-size); height: var(--control-size);

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

function rules(source) {
    const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const out = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(clean)) !== null) {
        const selector = m[1].trim().replace(/\s+/g, ' ');
        if (!selector || selector.startsWith('@')) continue;
        out.push({ selector, body: m[2] });
    }
    return out;
}

function rule(all, selector) {
    const found = all.filter((r) => r.selector === selector);
    assert.equal(found.length, 1, `expected exactly one \`${selector}\` rule, found ${found.length}`);
    return found[0];
}

function baseRule(all, selector) {
    const found = all.find((r) => r.selector === selector);
    assert.ok(found, `no \`${selector}\` rule found`);
    return found;
}

function decl(r, prop) {
    const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`, 'i').exec(r.body);
    return m ? m[1].trim() : null;
}

const styles = read('client', 'css', 'styles.css');
const styleRules = rules(styles);

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the default marker is a flat block, not a rounded outlined chip', () => {
    const badge = rule(styleRules, '.settings-wrapper-badge');
    assert.equal(decl(badge, 'border-radius'), '0',
        'it was var(--radius-sm, 4px) on a 17px-tall outlined chip');
    assert.equal(decl(badge, 'border'), 'none',
        'the outline was half of what made it read as a lozenge');
});

test('the default marker uses the same cue set as the active tab', () => {
    const badge = rule(styleRules, '.settings-wrapper-badge');
    assert.equal(decl(badge, 'color'), 'var(--color-fg)',
        'was --color-accent, which is 2.86:1 on calming and 1.28:1 on snes; '
        + '--color-fg over the tint measures 10.83 and 7.16 respectively');
    assert.equal(decl(badge, 'background'), 'var(--color-accent-bg-soft)');
    assert.equal(decl(badge, 'border-bottom'), '2px solid var(--color-accent)',
        'accent stays as a marker, never as a glyph');
    assert.equal(decl(badge, 'font-weight'), 'bold');
});

test('the model annotation is neither a chip nor a state marker', () => {
    const model = rule(styleRules, '.settings-wrapper-badge-model');
    assert.equal(decl(model, 'border-radius'), '0');
    assert.equal(decl(model, 'border'), 'none');
    assert.equal(decl(model, 'background'), 'none',
        'it must not borrow the default marker\'s tint - "takes model" is a '
        + 'property of the wrapper, not a selected state');
    assert.equal(decl(model, 'border-left'), '1px solid var(--color-border)',
        'a hairline is what keeps it a separate field once the chip is gone');
    assert.equal(decl(model, 'color'), 'var(--color-fg-muted)');
});

test('the family count is a bare numeral parked at the end of the heading', () => {
    const count = rule(styleRules, '.settings-wrapper-family-count');
    assert.equal(decl(count, 'border-radius'), '0');
    assert.equal(decl(count, 'border'), 'none');
    assert.equal(decl(count, 'background'), 'none');
    assert.equal(decl(count, 'margin-left'), 'auto',
        'right-aligned under the heading rule, the table-header idiom - the '
        + 'count is still shown, it just has no box round it');
});

test('the family heading still reads as a grouping heading', () => {
    const title = rule(styleRules, '.settings-wrapper-family-title');
    assert.equal(decl(title, 'border-bottom'), '1px solid var(--color-border)',
        'the chip used to supply the "this is a heading" signal; with it gone '
        + 'the rule under the title has to');
    assert.equal(decl(title, 'color'), 'var(--oc-text-primary)',
        'a heading is not the accent; the rule under it does the grouping');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('no settings-screen class declares a pill or full radius', () => {
    const offenders = styleRules
        .filter((r) => /\.settings-[\w-]*/.test(r.selector))
        .filter((r) => {
            const v = decl(r, 'border-radius');
            return v !== null && /radius-pill|radius-full|9999px|999px|50%/.test(v);
        })
        .map((r) => r.selector);
    assert.deepEqual(offenders, [],
        `these settings selectors are lozenges: ${offenders.join(', ')}`);
});

test('every settings-screen <button> class declares its own radius', () => {
    const base = read('web', 'src', 'lib', 'base', 'elements.css');
    const boxRule = rules(base).find((r) => r.selector.includes('.modal-btn-danger')
        && decl(r, 'border-radius') !== null);
    assert.ok(boxRule, 'no base-recipe rule names .modal-btn-danger and declares border-radius');
    assert.equal(decl(boxRule, 'border-radius'), 'var(--_btn-radius)');
    assert.ok(boxRule.selector.includes('.modal-btn,') || boxRule.selector.includes(', .modal-btn'),
        'the base recipe box rule must also cover .modal-btn');
    const radiusRule = rules(base).find((r) => r.selector.includes('.modal-btn-danger')
        && decl(r, '--_btn-radius') !== null);
    assert.ok(radiusRule, 'no base-recipe rule sets --_btn-radius for the modal button family');
    assert.ok(!/radius-pill|radius-full|9999px|999px|50%/.test(decl(radiusRule, '--_btn-radius')),
        '--_btn-radius must not be a pill or full radius');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
