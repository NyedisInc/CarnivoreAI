
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadFamilyIcon() {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'agent-family-icon.js'), 'utf8');
    const ctx = { window: {}, console: { log() {} } };
    vm.createContext(ctx);
    vm.runInContext(src, ctx);
    return ctx.window.AgentFamilyIcon;
}

const FamilyIcon = loadFamilyIcon();
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

/* viewBox="0 0 16 16" */
function assertWellFormedMark(svgString) {
    assert.equal(typeof svgString, 'string', 'must return a string');
    assert.match(svgString, /^<svg[^>]*>[\s\S]*<\/svg>$/, 'must be one <svg>...</svg> element');
    assert.match(svgString, /viewBox="[^"]+"/, 'must carry a viewBox');
    assert.doesNotMatch(svgString, /<script/i, 'must carry no <script');
    assert.doesNotMatch(svgString, /\son[a-z]+\s*=/i, 'must carry no on* handler attribute');
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('assertWellFormedMark REJECTS an onerror handler', () => {
    assert.throws(() => assertWellFormedMark(
        '<svg viewBox="0 0 16 16"><image href="x" onerror="alert(1)"/></svg>'));
});

test('assertWellFormedMark REJECTS a missing viewBox', () => {
    assert.throws(() => assertWellFormedMark('<svg width="14" height="14">' +
        '<circle cx="8" cy="8" r="4"/></svg>'));
});

test('assertWellFormedMark REJECTS an inline <script>', () => {
    assert.throws(() => assertWellFormedMark(
        '<svg viewBox="0 0 16 16"><script>alert(1)</script></svg>'));
});

test('assertWellFormedMark ACCEPTS an actually well-formed mark', () => {
    assertWellFormedMark('<svg width="14" height="14" viewBox="0 0 16 16" ' +
        'fill="none" aria-hidden="true"><circle cx="8" cy="8" r="4" ' +
        'fill="currentColor"/></svg>');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

const allKeys = [...FamilyIcon.FAMILIES, 'unknown', null, undefined, 'not-a-real-family'];

for (const family of allKeys) {
    test(`svg(${JSON.stringify(family)}) is a well-formed mark`, () => {
        assertWellFormedMark(FamilyIcon.svg(family));
    });
}

test('every family in FAMILIES renders DISTINCT markup from every other', () => {
    const rendered = FamilyIcon.FAMILIES.map((f) => FamilyIcon.svg(f));
    assert.equal(new Set(rendered).size, rendered.length, 'no two families share markup');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('no family emits an id attribute, and none references url(#...)', () => {
    for (const family of FamilyIcon.FAMILIES) {
        const svgString = FamilyIcon.svg(family);
        assert.doesNotMatch(svgString, /\sid=/, `${family} must carry no id`);
        assert.doesNotMatch(svgString, /url\(#/, `${family} must reference no url(#...)`);
        assert.doesNotMatch(svgString, /<linearGradient/, `${family} must define no gradient`);
    }
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('hermes follows currentColor, not a fixed literal, so it reads on ' +
    'both a light and a dark theme', () => {
    const svgString = FamilyIcon.svg('hermes');
    assert.match(svgString, /currentColor/, 'hermes must carry currentColor');
    assert.doesNotMatch(svgString, /fill:\s*white/i, 'the source\'s fixed white fill must not survive');
    assert.doesNotMatch(svgString, /#fff(?:fff)?\b/i, 'no fixed white literal either');
});

test('openclaw keeps its brand reds as flat literals', () => {
    const svgString = FamilyIcon.svg('openclaw');
    assert.match(svgString, /#ff4d4d/i, 'openclaw must keep its bright brand red');
    assert.match(svgString, /#991b1b/i, 'openclaw must keep its darker brand red');
});

test('hermes and openclaw both carry a real viewBox and render at the default 14px', () => {
    for (const family of ['hermes', 'openclaw']) {
        const svgString = FamilyIcon.svg(family);
        assert.match(svgString, /width="14" height="14"/, `${family} must default to 14px`);
        assert.match(svgString, /viewBox="0 0 16 16"/, `${family} must use the module's 16-unit box`);
    }
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('DEFAULT_SIZE is still 14 and svg() honours an explicit size', () => {
    assert.equal(FamilyIcon.DEFAULT_SIZE, 14);
    assert.match(FamilyIcon.svg('claude', 20), /width="20" height="20"/);
});

test('normalize() still falls back to "unknown" for anything unrecognised', () => {
    assert.equal(FamilyIcon.normalize('not-a-real-family'), 'unknown');
    assert.equal(FamilyIcon.normalize(null), 'unknown');
    assert.equal(FamilyIcon.normalize(undefined), 'unknown');
});

test('labelFor() still names every family out loud, hermes and openclaw included', () => {
    assert.equal(FamilyIcon.labelFor('hermes'), 'hermes');
    assert.equal(FamilyIcon.labelFor('openclaw'), 'openclaw');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
