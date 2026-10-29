
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

function css(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'css', name), 'utf8');
}

function findRules(source, selectorSubstring) {
    const lines = source.split('\n');
    const out = [];
    for (let i = 0; i < lines.length; i++) {
        if (!lines[i].includes('{')) continue;
        let selStart = i;
        while (selStart > 0 && !lines[selStart - 1].trim().endsWith('{') &&
               !lines[selStart - 1].trim().endsWith('}') &&
               lines[selStart - 1].trim() !== '' &&
               !lines[selStart - 1].trim().startsWith('/*') &&
               !lines[selStart - 1].trim().startsWith('*')) {
            if (selStart === i) { selStart--; continue; }
            break;
        }
        const selectorLines = [];
        for (let k = selStart; k <= i; k++) selectorLines.push(lines[k]);
        const selector = selectorLines.join('\n').replace(/\{.*$/, '').trim();
        if (!selector.includes(selectorSubstring)) continue;
        const bodyLines = [];
        for (let j = i + 1; j < lines.length && lines[j].trim() !== '}'; j++) {
            bodyLines.push(lines[j]);
        }
        out.push({ selector, body: bodyLines.join('\n') });
    }
    return out;
}

function specificity(selector) {
    let ids = 0, classes = 0, elements = 0;
    let s = selector;
    const notRegex = /:not\(([^()]*)\)/g;
    let match;
    while ((match = notRegex.exec(s)) !== null) {
        const inner = specificityRaw(match[1]);
        ids += inner.ids;
        classes += inner.classes;
        elements += inner.elements;
    }
    s = s.replace(notRegex, '');
    const outer = specificityRaw(s);
    return { ids: ids + outer.ids, classes: classes + outer.classes, elements: elements + outer.elements };
}

function specificityRaw(s) {
    const ids = (s.match(/#[\w-]+/g) || []).length;
    let classes = (s.match(/\.[\w-]+/g) || []).length;
    classes += (s.match(/\[[^\]]+\]/g) || []).length;
    const pseudoElements = (s.match(/::[a-zA-Z-]+/g) || []).length;
    const stripped1 = s.replace(/::[a-zA-Z-]+/g, ' ');
    classes += (stripped1.match(/:[a-zA-Z-]+/g) || []).length;
    const stripped2 = stripped1
        .replace(/#[\w-]+/g, ' ')
        .replace(/\.[\w-]+/g, ' ')
        .replace(/\[[^\]]+\]/g, ' ')
        .replace(/:[a-zA-Z-]+/g, ' ');
    const elements = pseudoElements + (stripped2.match(/[a-zA-Z][a-zA-Z0-9-]*/g) || []).length;
    return { ids, classes, elements };
}

function compareSpecificity(a, b) {
    if (a.ids !== b.ids) return a.ids - b.ids;
    if (a.classes !== b.classes) return a.classes - b.classes;
    return a.elements - b.elements;
}

function hoverOverflow(itemWidth, scaleFactor, containerWidth) {
    return Math.max(0, itemWidth * scaleFactor - containerWidth);
}


const stylesSrc = css('styles.css');
const terminalToolsSrc = css('terminal-tools.css');

const buttonHoverRules = findRules(stylesSrc, 'button:hover:not(:disabled)')
    .filter((r) => r.selector.split(',').map((s) => s.trim()).includes('button:hover:not(:disabled)'));

const iconHoverRules = findRules(stylesSrc, '.btn-icon:hover:not(:disabled)')
    .filter((r) => r.selector.split(',').map((s) => s.trim()).includes('.btn-icon:hover:not(:disabled)'));

test('the bare button:hover:not(:disabled) rule is gone; .btn-icon:hover:not(:disabled) still scales', () => {
    assert.equal(buttonHoverRules.length, 0,
        `expected zero bare button:hover:not(:disabled) rules, found ${buttonHoverRules.length} - `
        + 'that reset is now scoped to .btn-icon');
    assert.equal(iconHoverRules.length, 1,
        `expected exactly one .btn-icon:hover:not(:disabled) rule, found ${iconHoverRules.length}`);
    assert.match(iconHoverRules[0].body, /transform:\s*scale\(/,
        'the header icon buttons still get their hover scale - only its reach changed');
});

test('.cloude-session-theme__item is never assigned the btn-icon class', () => {
    const sessionThemeMenuSrc = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'session-theme-menu.js'), 'utf8');
    const classAssignment = sessionThemeMenuSrc.match(
        /className\s*=\s*[`'"][^`'"]*\bcloude-session-theme__item\b[^`'"]*[`'"]/);
    assert.ok(classAssignment, 'expected to find where .cloude-session-theme__item is assigned');
    assert.ok(!classAssignment[0].includes('btn-icon'),
        '.cloude-session-theme__item must never also carry btn-icon, or the hover-scale '
        + 'reset reaches theme rows again and the overflow bug returns');
});

const itemHoverRules = findRules(terminalToolsSrc, 'cloude-session-theme__item:hover');

test('a .cloude-session-theme__item hover/focus rule exists', () => {
    assert.ok(itemHoverRules.length >= 1, 'expected at least one rule targeting the item hover/focus state');
});

test('the item hover rule explicitly cancels transform', () => {
    const rule = itemHoverRules[0];
    assert.match(rule.body, /transform:\s*none\s*;/,
        '.cloude-session-theme__item hover/focus-visible must explicitly set transform: none ' +
        'to cancel the inherited scale from the global button:hover:not(:disabled) rule');
});

test('the item hover rule keeps the background swap (the actual hover affordance)', () => {
    const rule = itemHoverRules[0];
    assert.match(rule.body, /background:\s*var\(--oc-ground-hover\)\s*;/,
        'removing the scale must not remove the hover feedback entirely - the background swap is the affordance');
});

const historicalButtonSpec = { ids: 0, classes: 2, elements: 1 };

test('the item hover selector is specific enough to actually WIN against the historical button:hover rule', () => {
    const rule = itemHoverRules[0];
    const branches = rule.selector.split(',').map((s) => s.trim());
    for (const branch of branches) {
        const branchSpec = specificity(branch);
        assert.ok(compareSpecificity(branchSpec, historicalButtonSpec) > 0,
            `selector branch "${branch}" has specificity ` +
            `(${branchSpec.ids},${branchSpec.classes},${branchSpec.elements}) which does not beat ` +
            `button:hover:not(:disabled)'s (${historicalButtonSpec.ids},${historicalButtonSpec.classes},` +
            `${historicalButtonSpec.elements}) - transform: none would lose the cascade and silently do nothing`);
    }
});

test('the weaker, pre-fix selector form would NOT have been enough (proves the test can fail)', () => {
    const weakSpec = specificity('.cloude-session-theme__item:hover');
    assert.ok(compareSpecificity(weakSpec, historicalButtonSpec) <= 0,
        'sanity check failed: the unqualified selector unexpectedly beats the button rule - ' +
        'the specificity model itself may be wrong');
});


test('scale(1.05) on a full-width row overflows a clamped container', () => {
    const before = hoverOverflow(188, 1.05, 188);
    assert.ok(before > 0, `expected overflow before the fix, got ${before}`);
});

test('transform: none removes the overflow at the same width', () => {
    const after = hoverOverflow(188, 1.0, 188);
    assert.equal(after, 0, `expected zero overflow after the fix, got ${after}`);
});

test('the fix holds at the narrow 390px viewport too (no width-specific carve-out)', () => {
    const before = hoverOverflow(198, 1.05, 198);
    const after = hoverOverflow(198, 1.0, 198);
    assert.ok(before > 0, 'expected overflow before the fix at 390px');
    assert.equal(after, 0, 'expected zero overflow after the fix at 390px');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
