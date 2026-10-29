
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { installEnv, loadEffect, effectThemes } from './helpers/fake-theme-dom.mjs';
import { trackInk, styleAlpha } from './helpers/ink-probe.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');
const cssRoot = path.join(repoRoot, 'client', 'css');

let failures = 0;
let passes = 0;

/**
 * Run one named assertion, recording the outcome.
 * @param {string} name Test name shown in the output
 * @param {function(): void} fn Body; throws to fail
 * @returns {void}
 */
function test(name, fn) {
    try {
        fn();
        passes++;
        console.log('ok - ' + name);
    } catch (err) {
        failures++;
        console.error('NOT OK - ' + name);
        console.error(err && err.stack ? err.stack : err);
    }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

function cssFiles(dir) {
    const out = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            if (entry.name === 'vendor') continue;
            out.push(...cssFiles(p));
        } else if (entry.name.endsWith('.css')) {
            out.push(p);
        }
    }
    return out;
}

function stripComments(css) {
    return css.replace(/\/\*[\s\S]*?\*\//g, ' ');
}

function rules(css) {
    const out = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(css)) !== null) {
        const selector = m[1].split('}').pop().trim();
        if (!selector || selector.startsWith('@')) continue;
        out.push({ selector, body: m[2] });
    }
    return out;
}

function subjectIsBody(selector) {
    const last = selector.trim().split(/\s|>|\+|~/).filter(Boolean).pop() || '';
    return /^body(?:[:[.#].*)?$/.test(last) && !/::/.test(last);
}

const allCss = cssFiles(cssRoot).map((f) => ({
    file: path.relative(repoRoot, f),
    text: stripComments(fs.readFileSync(f, 'utf8')),
}));

test('no stylesheet gives body a background - it would occlude the effects canvas', () => {
    const offenders = [];
    for (const { file, text } of allCss) {
        for (const rule of rules(text)) {
            for (const sel of rule.selector.split(',')) {
                if (!subjectIsBody(sel)) continue;
                const decls = rule.body.split(';');
                for (const d of decls) {
                    const [propRaw, valRaw] = d.split(':');
                    if (!propRaw || !valRaw) continue;
                    const prop = propRaw.trim().toLowerCase();
                    const val = valRaw.trim().toLowerCase();
                    if (prop !== 'background' && prop !== 'background-color') continue;
                    if (val === 'transparent' || val === 'none') continue;
                    offenders.push(`${file}: "${sel.trim()}" sets ${prop}: ${val}`);
                }
            }
        }
    }
    assert.deepEqual(
        offenders,
        [],
        'body must stay transparent so the z-index:-1 effects canvas is not '
        + 'painted over. Move the declaration to the root '
        + '(`:root[data-theme="x"]`). Offenders:\n  ' + offenders.join('\n  '),
    );
});

test('the root paints the page background, so the page is not left blank', () => {
    const styles = allCss.find((c) => c.file.endsWith('css/styles.css'));
    assert.ok(styles, 'client/css/styles.css not found');
    const rootRules = rules(styles.text).filter(
        (r) => r.selector.split(',').some((s) => ['html', ':root'].includes(s.trim())),
    );
    const painting = rootRules.filter((r) => /(^|;)\s*background(-color)?\s*:/.test(r.body));
    assert.ok(
        painting.length > 0,
        'styles.css must give html/:root a background - it is what the user '
        + 'sees now that body is transparent',
    );
    assert.match(
        painting.map((r) => r.body).join(';'),
        /var\(\s*--color-bg\b/,
        'the root must paint --color-bg, the theme page colour. It must NOT '
        + 'use --color-bg-page, which is the darker header/chrome colour and '
        + 'differs from --color-bg in 18 of the 23 shipped themes',
    );
});

test('no stylesheet re-declares a competing root background with --color-bg-page', () => {
    const offenders = [];
    for (const { file, text } of allCss) {
        if (file.endsWith('css/styles.css')) continue;
        for (const rule of rules(text)) {
            const isRoot = rule.selector.split(',').some(
                (s) => ['html', ':root'].includes(s.trim()),
            );
            if (!isRoot) continue;
            if (/background(-color)?\s*:[^;]*--color-bg-page/.test(rule.body)) {
                offenders.push(`${file}: "${rule.selector.trim()}"`);
            }
        }
    }
    assert.deepEqual(offenders, [], 'competing root background rules:\n  ' + offenders.join('\n  '));
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

const baseline = JSON.parse(fs.readFileSync(
    path.join(repoRoot, 'tests', 'fixtures', 'theme-effect-visibility-baseline.json'),
    'utf8',
));

const VISIBLE_FLOOR = baseline.visibleFloor;

const ALPHA_TOLERANCE = 0.85;

const FRAMES = 120;

test('every effect theme has a measured visibility baseline', () => {
    const declared = new Set(Object.keys(baseline.themes));
    const missing = effectThemes.filter((t) => !declared.has(t));
    const stale = [...declared].filter((t) => !effectThemes.includes(t));
    assert.deepEqual(missing, [], 'themes ship an effect but have no measured baseline: ' + missing);
    assert.deepEqual(stale, [], 'baseline names themes that no longer ship an effect: ' + stale);
});

test('the recorded baseline proves every theme was measured visible', () => {
    const weak = [];
    for (const [id, row] of Object.entries(baseline.themes)) {
        if (row.measuredMaxDelta < VISIBLE_FLOOR) {
            weak.push(`${id}: ${row.measuredMaxDelta}/255`);
        }
        assert.equal(
            row.noiseFloorMaxDelta, 0,
            `${id}: baseline was taken with a noise floor of `
            + `${row.noiseFloorMaxDelta}, so its delta is not trustworthy`,
        );
    }
    assert.deepEqual(
        weak, [],
        `these themes were recorded below the ${VISIBLE_FLOOR}/255 visibility `
        + 'floor:\n  ' + weak.join('\n  '),
    );
});

test('ink probe: styleAlpha reads the forms the effects actually use', () => {
    assert.equal(styleAlpha('rgba(1, 2, 3, 0.025)'), 0.025);
    assert.equal(styleAlpha('rgba(1,2,3,0)'), 0);
    assert.equal(styleAlpha('#33FF33'), 1);
    assert.equal(styleAlpha('#33FF3380'), 128 / 255);
    assert.equal(styleAlpha('transparent'), 0);
    assert.equal(styleAlpha(null), 0);
    assert.equal(styleAlpha({ stops: [{ color: 'rgba(0,0,0,0)' }, { color: 'rgba(0,0,0,0.05)' }] }), 0.05);
    assert.equal(styleAlpha({ stops: [] }), 0);
});

const modules = new Map();
for (const id of effectThemes) modules.set(id, await loadEffect(id));

for (const themeId of effectThemes) {
    test(`${themeId}: deposits enough ink to be perceptible, not merely to run`, () => {
        const env = installEnv();
        const mod = modules.get(themeId);
        assert.ok(mod, `effects module for ${themeId} did not load`);

        mod.init({ themeContext: { id: themeId, manifest: {} } });
        const canvas = env.canvas();
        assert.ok(canvas, `${themeId} mounted no canvas`);
        const ctx = canvas._ctx;
        assert.ok(ctx, `${themeId} acquired no 2D context`);

        const ink = trackInk(ctx);
        for (let i = 0; i < FRAMES; i++) env.flush(i * 33);

        const decorative = ink.decorativeCount();
        const peak = ink.peakDecorative();

        assert.notEqual(
            decorative, 0,
            `${themeId}: CANNOT EVALUATE - no decorative mark in ${FRAMES} `
            + 'frames. Every mark was a full-canvas opaque fill, so this probe '
            + 'cannot say whether anything is visible. Check the effect by '
            + 'screenshot before assuming it is fine.',
        );

        const recorded = baseline.themes[themeId].decorativeAlpha;
        assert.ok(
            peak >= recorded * ALPHA_TOLERANCE,
            `${themeId}: peak decorative alpha fell from a measured ${recorded} `
            + `to ${peak.toFixed(4)}. The recorded value is the one that was `
            + `proven to composite ${baseline.themes[themeId].measuredMaxDelta}/255 `
            + 'in a browser; dimming below it makes that proof stale. If the '
            + 'change is intended, re-run scripts/verify/'
            + 'measure-theme-effect-visibility.py, LOOK at the screenshots, and '
            + 'commit the new baseline.',
        );

        mod.destroy();
    });
}

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
