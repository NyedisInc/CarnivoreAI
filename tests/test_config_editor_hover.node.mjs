
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

function specificity(selector) {
    let s = selector.trim();
    let b = 0;
    s = s.replace(/:where\([^)]*\)/g, ' ');
    s = s.replace(/:(?:not|is)\(([^)]*)\)/g, (_all, inner) => ' ' + inner + ' ');
    const ids = (s.match(/#[\w-]+/g) || []).length;
    b += (s.match(/\.[\w-]+/g) || []).length;
    b += (s.match(/\[[^\]]*\]/g) || []).length;
    s = s.replace(/::[\w-]+/g, ' PSEUDOEL ');
    b += (s.match(/:[\w-]+/g) || []).length;
    const stripped = s.replace(/#[\w-]+|\.[\w-]+|\[[^\]]*\]|:[\w-]+/g, ' ');
    const els = (stripped.match(/[\w-]+/g) || []).filter((t) => t !== 'PSEUDOEL').length
        + (s.match(/::[\w-]+/g) || []).length;
    return [ids, b, els];
}

function cmp(a, b) {
    for (let i = 0; i < 3; i++) {
        if (a[i] !== b[i]) return a[i] - b[i];
    }
    return 0;
}

const ROW_CLASSES = ['config-editor-toggle', 'config-editor-file'];

const GEOMETRY_PROPS = [
    'transform', 'box-shadow', 'padding', 'padding-left', 'padding-right',
    'margin', 'margin-left', 'margin-right', 'width', 'min-width',
    'border', 'border-width', 'border-left-width', 'border-right-width',
    'scale', 'zoom',
];

const editorCss = css('config-editor.css');
const stylesCss = css('styles.css');
const editorRules = rules(editorCss);
const styleRules = rules(stylesCss);

function rowHoverRules(ruleList, bareButton) {
    const out = [];
    for (const r of ruleList) {
        for (const sel of r.selector.split(',')) {
            const s = sel.trim();
            if (!s.includes(':hover')) continue;
            const isRow = ROW_CLASSES.some((c) => s.includes(c));
            const isBare = bareButton && /^button(?![\w-])/.test(s);
            if (isRow || isBare) out.push({ selector: s, body: r.body });
        }
    }
    return out;
}


test('the tree-row hover rule cancels the reset transform and outset glow', () => {
    const hits = rowHoverRules(editorRules, false)
        .filter((r) => /transform:\s*none/.test(r.body));
    assert.ok(hits.length > 0,
        'a :hover rule on a tree row must declare transform: none, or the '
        + 'bare button reset scales the row wider than the tree');
    for (const h of hits) {
        assert.match(h.body, /box-shadow:\s*none\s*;/,
            `${h.selector} must also cancel the reset's outset glow`);
    }
});

test('the bare button hover reset is gone, and the row classes never opt into its replacement', () => {
    const reset = styleRules
        .flatMap((r) => r.selector.split(',').map((s) => ({ selector: s.trim(), body: r.body })))
        .filter((r) => /^button:hover/.test(r.selector) && /transform:/.test(r.body));
    assert.deepEqual(reset, [],
        'expected zero bare `button:hover` rules in styles.css - that reset '
        + 'is now scoped to .btn-icon');

    const configEditorPanelJs = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'config-editor-panel.js'), 'utf8');
    for (const cls of ROW_CLASSES) {
        const classAssignment = new RegExp(
            `className\\s*=\\s*[\`'"][^\`'"]*\\b${cls}\\b[^\`'"]*[\`'"]`);
        const m = configEditorPanelJs.match(classAssignment);
        assert.ok(m, `expected to find where .${cls} is assigned in config-editor-panel.js`);
        assert.ok(!m[0].includes('btn-icon'),
            `.${cls} must never also carry btn-icon, or the round-icon reset `
            + 'reaches tree rows again and the overflow bug returns');
    }

    const historicalResetSpec = [0, 2, 1];
    for (const cls of ROW_CLASSES) {
        const guard = rowHoverRules(editorRules, false)
            .filter((r) => r.selector.includes(cls) && /transform:\s*none/.test(r.body));
        assert.ok(guard.length > 0, `no transform-cancelling hover rule for .${cls}`);
        const best = guard
            .map((r) => specificity(r.selector))
            .reduce((a, b) => (cmp(a, b) >= 0 ? a : b));
        assert.ok(cmp(best, historicalResetSpec) > 0,
            `.${cls} hover guard specificity ${best} does not beat ${historicalResetSpec}; `
            + 'add :not(:disabled) rather than !important');
    }
});

test('no tree-row hover rule adds width, padding, border or an outset shadow', () => {
    for (const r of rowHoverRules(editorRules, false)) {
        for (const prop of GEOMETRY_PROPS) {
            const re = new RegExp(`(^|;|\\s)${prop}\\s*:\\s*([^;]+)`, 'i');
            const m = r.body.match(re);
            if (!m) continue;
            const value = m[2].trim();
            assert.ok(value === 'none' || value === '0',
                `${r.selector} sets ${prop}: ${value} on hover; a hover `
                + 'affordance must fit inside the row it already occupies');
        }
    }
});

test('the focus ring is inset, so keyboard focus adds no width either', () => {
    const focusRules = editorRules
        .flatMap((r) => r.selector.split(',').map((s) => ({ selector: s.trim(), body: r.body })))
        .filter((r) => ROW_CLASSES.some((c) => r.selector.includes(c))
            && r.selector.includes(':focus-visible')
            && (r.body.match(/box-shadow:\s*([^;]+)/) || [])[1]?.trim() !== 'none'
            && /box-shadow:/.test(r.body));
    assert.ok(focusRules.length > 0, 'the tree rows must keep a visible focus ring');
    for (const r of focusRules) {
        assert.match(r.body, /box-shadow:\s*inset\s/,
            `${r.selector} must use an inset ring; an outset one overflows the tree`);
    }
});

test('the focus ring survives the box-shadow: none neutralizer', () => {
    const zeroing = rowHoverRules(editorRules, false)
        .filter((r) => /box-shadow:\s*none/.test(r.body))
        .map((r) => specificity(r.selector))
        .reduce((a, b) => (cmp(a, b) >= 0 ? a : b), [0, 0, 0]);
    const ring = editorRules
        .flatMap((r) => r.selector.split(',').map((s) => ({ selector: s.trim(), body: r.body })))
        .filter((r) => ROW_CLASSES.some((c) => r.selector.includes(c))
            && /box-shadow:\s*inset\s/.test(r.body))
        .map((r) => specificity(r.selector))
        .reduce((a, b) => (cmp(a, b) >= 0 ? a : b), [0, 0, 0]);
    assert.ok(cmp(ring, zeroing) >= 0,
        `focus-ring specificity ${ring} loses to the box-shadow: none rule ${zeroing}`);
});


test('the tree scrolls, so any row overhang is a real horizontal scrollbar', () => {
    const tree = editorRules.find((r) => r.selector === '.config-editor-tree');
    assert.ok(tree, '.config-editor-tree rule not found');
    assert.match(tree.body, /overflow-y:\s*auto\s*;/,
        'the tree scrolls vertically, which per CSS overflow-3 makes the '
        + 'horizontal axis auto as well - that is why this guard exists');
});

test('the row name still shrinks - the badge-alignment fix is intact', () => {
    const name = editorRules.find((r) => r.selector === '.config-editor-node-name');
    assert.ok(name, '.config-editor-node-name rule not found');
    assert.match(name.body, /min-width:\s*0\s*;/,
        'min-width: 0 is load-bearing for badge-row alignment; do not remove it');
    assert.match(name.body, /text-overflow:\s*ellipsis\s*;/);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
