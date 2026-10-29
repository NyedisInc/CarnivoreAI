
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

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
 * Read one file from the repo.
 * @param {...string} parts  Path segments below the repo root.
 * @returns {string} File contents.
 */
function read(...parts) {
    return fs.readFileSync(path.join(ROOT, ...parts), 'utf8');
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

function ruleBody(list, selector) {
    for (const r of list) {
        const parts = r.selector.split(',').map((s) => s.trim());
        if (parts.includes(selector)) return r.body;
    }
    return '';
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

/**
 * Compare two specificity triples.
 * @param {[number, number, number]} a  Left triple.
 * @param {[number, number, number]} b  Right triple.
 * @returns {number} Negative if a < b, 0 if equal, positive if a > b.
 */
function cmp(a, b) {
    for (let i = 0; i < 3; i++) {
        if (a[i] !== b[i]) return a[i] - b[i];
    }
    return 0;
}

const homeBarCss = read('client', 'css', 'home-bar.css');
const iosCss = read('client', 'css', 'ios-chrome.css');
const stylesCss = read('client', 'css', 'styles.css');
const indexHtml = read('client', 'index.html');
// SLICE 7: `client/js/launchpad.js` is gone. The home screen's
// markup and its wiring are the Svelte shell and the modules
// beside it; every assertion below is unchanged and simply reads
// the files that now hold what it is about.
const apiJs = read('client', 'js', 'api.js');

const homeBarRules = rules(homeBarCss);
const iosRules = rules(iosCss);
const styleRules = rules(stylesCss);

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the bar is a non-shrinking full-width row', () => {
    const body = ruleBody(homeBarRules, '.home-bar');
    assert.ok(body, '.home-bar rule not found');
    assert.match(body, /display:\s*flex\s*;/);
    assert.match(body, /align-items:\s*center\s*;/);
    assert.match(body, /flex-shrink:\s*0\s*;/,
        'the bar is a flex item of #launchpad-screen; without this the '
        + 'project list squeezes it to nothing');
    assert.match(body, /width:\s*100%\s*;/);
});

test('the bar height is built from the two tokens, not a literal', () => {
    const body = ruleBody(homeBarRules, '.home-bar');
    assert.match(body, /height:\s*calc\(\s*var\(--home-bar-h\)\s*\+\s*var\(--home-bar-inset\)\s*\)/,
        'box-sizing is border-box app-wide, so the safe-area inset has to '
        + 'be ADDED to the height as well as applied as padding, or it '
        + 'eats the content height instead of extending the box below it');
    assert.match(body, /padding:[^;]*var\(--home-bar-inset\)/,
        'the inset must also be padding, so the bar background paints over '
        + 'the home-indicator strip while its contents stay above it');
});

test('the bar stays thin: no vertical padding of its own', () => {
    const body = ruleBody(homeBarRules, '.home-bar');
    const pad = (body.match(/(^|;|\s)padding\s*:\s*([^;]+)/) || [])[2];
    assert.ok(pad, '.home-bar must declare padding explicitly');
    const parts = pad.trim().split(/\s+(?![^(]*\))/);
    assert.equal(parts[0], '0',
        `padding-top is "${parts[0]}"; the bar's height IS its content `
        + 'height, and vertical padding is exactly the thing that makes a '
        + 'bottom bar fat');
});

test('the coarse-pointer bump exists and reaches the 44px touch minimum', () => {
    const block = homeBarCss.match(/@media\s*\(pointer:\s*coarse\)\s*\{([\s\S]*?)\n\}/);
    assert.ok(block, 'no @media (pointer: coarse) block in home-bar.css');
    assert.match(block[1], /--home-bar-h:\s*44px\s*;/,
        'a coarse pointer needs a 44px target (Apple HIG / WCAG 2.5.5)');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('every interactive bar item declares BOTH width and height', () => {
    const rule = homeBarRules.find((r) => r.selector.includes('.home-bar__btn')
        && r.selector.includes('.home-bar__link')
        && /width:/.test(r.body));
    assert.ok(rule, 'no shared geometry rule for .home-bar__btn/.home-bar__link');
    assert.match(rule.body, /(^|;|\s)width:\s*var\(--home-bar-h\)\s*;/);
    assert.match(rule.body, /(^|;|\s)height:\s*var\(--home-bar-h\)\s*;/);
    assert.match(rule.body, /box-sizing:\s*border-box\s*;/);
});

test('the hover guard cancels the reset transform and outset glow', () => {
    const guards = homeBarRules.filter((r) => /transform:\s*none/.test(r.body)
        && r.selector.includes('.home-bar__btn'));
    assert.ok(guards.length > 0,
        'a :hover rule on a bar item must declare transform: none, or the '
        + 'bare button reset scales it past the strip it lives in');
    for (const g of guards) {
        assert.match(g.body, /box-shadow:\s*none\s*;/,
            `${g.selector} must also cancel the reset's 12px outset glow, `
            + 'which bleeds over the content above a bar this thin');
    }
});

test('the bare button hover reset is gone, and .home-bar__btn never opts into its replacement', () => {
    // SCOPING FIX. `button:hover:not(:disabled)` no longer exists - it is
    // `.btn-icon:hover:not(:disabled)` now, applied only to
    // `#configEditorBtn` and `.header-menu-toggle` (see
    const reset = styleRules
        .flatMap((r) => r.selector.split(',').map((s) => ({ selector: s.trim(), body: r.body })))
        .filter((r) => /^button:hover/.test(r.selector) && /transform:/.test(r.body));
    assert.deepEqual(reset, [],
        'expected zero bare `button:hover` rules in styles.css - that reset '
        + 'is now scoped to .btn-icon');


    // Keep the pre-existing specificity guard too, pinned against the
    // from.
    const historicalResetSpec = [0, 2, 1];
    const guard = homeBarRules
        .flatMap((r) => r.selector.split(',').map((s) => ({ selector: s.trim(), body: r.body })))
        .filter((r) => r.selector.includes('.home-bar__btn')
            && r.selector.includes(':hover')
            && /transform:\s*none/.test(r.body))
        .map((r) => specificity(r.selector));
    assert.ok(guard.length > 0, 'no transform-cancelling hover rule for .home-bar__btn');
    const best = guard.reduce((a, b) => (cmp(a, b) >= 0 ? a : b));
    assert.ok(cmp(best, historicalResetSpec) > 0,
        `.home-bar__btn hover guard specificity ${best} does not beat ${historicalResetSpec}; `
        + 'add :not(:disabled) rather than !important');
});

test('the focus ring is inset, so it cannot paint over the content above', () => {
    const ring = homeBarRules.filter((r) => r.selector.includes(':focus-visible')
        && /box-shadow:\s*inset\s/.test(r.body));
    assert.ok(ring.length > 0,
        'the bar items must keep a visible keyboard focus ring, and it has '
        + 'to be inset: an item is exactly as tall as the bar, so an outset '
        + 'ring lands on the project list');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the spacer can actually collapse', () => {
    const body = ruleBody(homeBarRules, '.home-bar__spacer');
    assert.ok(body, '.home-bar__spacer rule not found');
    assert.match(body, /flex:\s*1\s+1\s+auto\s*;/);
    assert.match(body, /min-width:\s*0\s*;/,
        'a flex item defaults to min-width: auto, which is its CONTENT '
        + 'size; without this the spacer refuses to shrink and pushes the '
        + 'version and the link off a narrow screen');
});

test('the scroller takes the leftover height and can shrink below content', () => {
    const body = ruleBody(homeBarRules, '.launchpad-scroll');
    assert.ok(body, '.launchpad-scroll rule not found');
    assert.match(body, /flex:\s*1\s+1\s+auto\s*;/);
    assert.match(body, /min-height:\s*0\s*;/,
        'without this a long project list pushes the bar off the bottom of '
        + 'the viewport instead of scrolling inside its own box');
    assert.match(body, /overflow-y:\s*auto\s*;/);
});

test('the screen stops being the scroll container', () => {
    const body = ruleBody(homeBarRules, '#launchpad-screen');
    assert.ok(body, 'home-bar.css must retire #launchpad-screen as a scroller');
    assert.match(body, /overflow:\s*hidden\s*;/,
        '.screen in styles.css sets overflow: auto; if the screen still '
        + 'scrolls, the bar scrolls with the content and is not a bar');
    assert.match(body, /padding:\s*0\s+0\s+0\s+var\(--dock-offset,\s*0\)\s*;/,
        "the screen's 20px padding moves to the scroller, or the bar cannot "
        + 'reach the side edges');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('home-bar.css is self-contained: it defaults the inset token to 0', () => {
    const root = homeBarRules.find((r) => r.selector === ':root' && /--home-bar-inset/.test(r.body));
    assert.ok(root, 'home-bar.css must declare a --home-bar-inset default');
    assert.match(root.body, /--home-bar-inset:\s*0px\s*;/);
    const live = homeBarCss.replace(/\/\*[\s\S]*?\*\//g, '');
    assert.ok(!/env\(/.test(live),
        'home-bar.css must not read env() itself; ios-chrome.css is the one '
        + 'place in this app that does, and splitting that invariant is how '
        + 'inset handling drifts');
});

test('ios-chrome.css sets the real inset on :root, not on .home-bar', () => {
    const root = iosRules.find((r) => r.selector === ':root' && /--home-bar-inset/.test(r.body));
    assert.ok(root, 'ios-chrome.css must override --home-bar-inset');
    assert.match(root.body, /--home-bar-inset:\s*env\(safe-area-inset-bottom\)/);
    const onBar = iosRules.find((r) => r.selector === '.home-bar' && /--home-bar-inset/.test(r.body));
    assert.ok(!onBar,
        'do not set --home-bar-inset on .home-bar; it shadows the devtools '
        + 'override that is the only available verification of this rule');
});

test('the home screen is excluded from the generic screen bottom inset', () => {
    const generic = iosRules.find((r) => r.selector === '.screen');
    assert.ok(generic && /padding-bottom:\s*env\(safe-area-inset-bottom\)/.test(generic.body),
        'expected the generic .screen bottom inset in ios-chrome.css');
    const excluded = ruleBody(iosRules, '#launchpad-screen');
    assert.match(excluded, /padding-bottom:\s*0\s*;/,
        'the home screen owns its own inset through the bar; taking the '
        + 'generic one too parks a strip of bare page background under it');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('no client file renders the bar markup', () => {
    const clientDir = path.join(ROOT, 'client');
    const offenders = [];
    function walk(dir) {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                if (entry.name === 'vendor') continue;
                walk(full);
                continue;
            }
            if (!/\.(js|html)$/.test(entry.name)) continue;
            if (full.endsWith(path.join('dist', 'app.js'))) continue;
            if (/class="home-bar"/.test(fs.readFileSync(full, 'utf8'))) {
                offenders.push(path.relative(ROOT, full));
            }
        }
    }
    walk(clientDir);
    assert.deepEqual(offenders, [],
        'the bar must be rendered into #launchpad-screen and nowhere else; '
        + 'the terminal screen spends its vertical pixels on the terminal');
});

test('no rule in home-bar.css can reach the terminal screen', () => {
    for (const r of homeBarRules) {
        for (const sel of r.selector.split(',')) {
            const s = sel.trim();
            assert.ok(!/terminal/i.test(s),
                `${s} names the terminal; this stylesheet is home-screen only`);
        }
    }
});

test('the retired .launchpad-footer is gone from styles.css', () => {
    const dead = styleRules.filter((r) => r.selector.includes('.launchpad-footer'));
    assert.deepEqual(dead.map((r) => r.selector), [],
        'the bar is a different box in a different place, not a restyle of '
        + 'the old footer; leaving both invites the next edit into the wrong one');
    const resetBtn = styleRules.filter((r) => r.selector.includes('.reset-server-btn'));
    assert.deepEqual(resetBtn.map((r) => r.selector), [],
        'the "reset server" button moved into the server-controls menu; its '
        + 'styles must not linger');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the version chip left the header and is stamped through a meta tag', () => {
    const h1 = indexHtml.match(/<h1 id="appTitle">([\s\S]*?)<\/h1>/);
    assert.ok(h1, 'header h1 not found');
    assert.ok(!/class="version"/.test(h1[1]),
        'the version chip must not be back in the header: it is '
        + 'flex-shrink: 0, so every pixel it takes comes off the title '
        + "truncation budget on every screen including the terminal's");
    assert.match(indexHtml, /<meta name="cloude-app-version" content="\{\{VERSION\}\}">/,
        'src/main.py substitutes {{VERSION}} by plain string replace; the '
        + 'meta tag is how the runtime-built bar gets the value');
});

test('an unresolved version renders "version unknown", not a mystery gap', () => {
    const versionFooterJs = read('client', 'js', 'version-footer.js');
    assert.match(versionFooterJs, /UNKNOWN_TEXT\s*=\s*'version unknown'/,
        'the honest fallback text must exist and be named');
    const emptyRule = homeBarRules.find((r) => r.selector.includes('.home-bar__version:empty'));
    assert.equal(emptyRule, undefined,
        'the :empty rule is dead now that the chip never renders empty - '
        + 'a stale rule here would suggest the chip can still go blank');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the API client offers no server-restart at all', () => {
    assert.ok(!/\/server\/reset/.test(apiJs),
        'the API client must not call a route the server no longer serves - '
        + 'that is a 404 button in place of a 500 one');
});

// ---------------------------------------------------------------------
// Load order
// ---------------------------------------------------------------------

test('home-bar.css loads before ios-chrome.css', () => {
    const a = indexHtml.indexOf('/static/css/home-bar.css');
    const b = indexHtml.indexOf('/static/css/ios-chrome.css');
    assert.ok(a > -1 && b > -1, 'both stylesheets must be linked');
    assert.ok(a < b,
        'ios-chrome.css overrides --home-bar-inset and excludes '
        + '#launchpad-screen from the generic screen inset; it has to win');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
