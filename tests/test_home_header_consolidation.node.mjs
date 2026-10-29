// disagree.

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
    return null;
}

const stylesCss = read('client', 'css', 'styles.css');
const indexHtml = read('client', 'index.html');
// SLICE 7: `client/js/launchpad.js` is gone. The home screen's
// markup and its wiring are the Svelte shell and the modules
// beside it; every assertion below is unchanged and simply reads
// the files that now hold what it is about.
const appJs = read('client', 'js', 'app.js');

const styleRules = rules(stylesCss);

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the dead .launchpad-header / .launchpad-prompt CSS rules are removed', () => {
    assert.equal(ruleBody(styleRules, '.launchpad-header'), null,
        'a rule nobody renders any more is dead weight - remove, do not orphan');
    assert.equal(ruleBody(styleRules, '.launchpad-prompt'), null);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('#home-subheader exists inside .header, outside .header-row', () => {
    const headerIdx = indexHtml.indexOf('<div class="header">');
    const rowOpenIdx = indexHtml.indexOf('<div class="header-row">', headerIdx);
    const rowCloseIdx = indexHtml.indexOf('<!-- /.header-row -->', rowOpenIdx);
    const subheaderIdx = indexHtml.indexOf('id="home-subheader"', rowCloseIdx);
    assert.ok(headerIdx > -1 && rowOpenIdx > -1 && rowCloseIdx > -1 && subheaderIdx > -1,
        'expected .header > .header-row (closed) > #home-subheader, in that order');
});

test('.header-row wraps exactly the toggle, the title and the controls', () => {
    const rowOpenIdx = indexHtml.indexOf('<div class="header-row">');
    const rowCloseIdx = indexHtml.indexOf('<!-- /.header-row -->', rowOpenIdx);
    const rowContent = indexHtml.slice(rowOpenIdx, rowCloseIdx);
    assert.ok(rowContent.includes('id="session-sidebar-toggle"'));
    assert.ok(rowContent.includes('id="appTitle"'));
    assert.ok(rowContent.includes('class="controls"'));
    assert.ok(rowContent.includes('class="header-home-spacer"'),
        'the centring spacer must be a real DOM sibling inside the row - '
        + 'see the file banner for why a CSS Grid track is not enough');
});

test('setHeaderIdentity toggles .header--home and .home-header-active in lockstep, never one without the other', () => {
    const fnStart = appJs.indexOf('function setHeaderIdentity');
    assert.ok(fnStart > -1, 'setHeaderIdentity not found');
    const fnBody = appJs.slice(fnStart, fnStart + 2500);
    assert.match(fnBody, /if\s*\(opts\.subheader\)/);
    assert.match(fnBody, /headerRowEl\.classList\.add\('header--home'\)/);
    assert.match(fnBody, /document\.body\.classList\.add\('home-header-active'\)/);
    assert.match(fnBody, /headerRowEl\.classList\.remove\('header--home'\)/);
    assert.match(fnBody, /document\.body\.classList\.remove\('home-header-active'\)/);
    assert.notEqual(
        fnBody.match(/classList\.add\('([\w-]+)'\)/)[1],
        (fnBody.match(/classList\.add\('([\w-]+)'\)/g) || [])[1],
    );
});

test('showLaunchpad() is the only caller that passes a subheader', () => {
    const showLaunchpadIdx = appJs.indexOf('showLaunchpad() {');
    const showAuthIdx = appJs.indexOf('showAuth() {');
    assert.ok(showLaunchpadIdx > -1 && showAuthIdx > -1);
    // WINDOW WIDENED 2026-08-31. A fixed byte slice over a function
    // body is brittle: adding a comment inside showLaunchpad() pushes
    // the thing being asserted past the end and this reports a
    // FAILURE about the wrong subject entirely - the hook is still
    // there, the window just stopped covering it. Widened rather than
    // trimmed at the source, because shrinking a comment to fit a
    // test's magic number is fitting the code to the harness.
    const launchpadBody = appJs.slice(showLaunchpadIdx, showLaunchpadIdx + 7000);
    assert.match(launchpadBody, /subheader:\s*'select a project or create a new project'/);
    assert.match(launchpadBody, /title:\s*'Launcher'/);
    const authBody = appJs.slice(showAuthIdx, showAuthIdx + 1500);
    assert.ok(!authBody.includes('subheader:'),
        'the auth screen must not grow the header - only the launchpad does');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the spacer is hidden by default and only sized under .header--home', () => {
    const base = ruleBody(styleRules, '.header-home-spacer');
    assert.ok(base !== null, '.header-home-spacer base rule missing');
    assert.match(base, /display:\s*none\s*;/,
        'must never touch the terminal/auth header layout');

    const homeBody = ruleBody(styleRules, '.header--home .header-home-spacer');
    assert.ok(homeBody !== null, '.header--home .header-home-spacer rule missing');
    assert.match(homeBody, /visibility:\s*hidden\s*;/,
        'a real sized sibling, invisible to the eye AND assistive tech, '
        + 'not a display:none one header-title-fit.js would skip');
    assert.match(homeBody, /width:\s*var\(--home-header-flank-w\)\s*;/);
});

test('the title centres by growing/shrinking into real space, not a grid track', () => {
    const body = ruleBody(styleRules, '.header--home #appTitle');
    assert.ok(body !== null, '.header--home #appTitle rule missing');
    assert.match(body, /flex:\s*1\s+1\s+auto\s*;/,
        'must grow AND shrink - a fixed flex-basis reintroduces the '
        + 'JS/CSS budget mismatch this file exists to prevent');
    assert.match(body, /justify-content:\s*center\s*;/,
        'centres the icon+text pair within whatever room is actually left - '
        + 'real centring, not a hardcoded margin that only looks right at one width');
    assert.ok(!/grid-column/.test(body),
        'must not regress to the grid-track approach - see the file banner');
});

test('--home-header-flank-w mirrors .controls\' real width: two inline buttons', () => {
    const body = ruleBody(styleRules, '.header--home');
    assert.ok(body !== null, '.header--home rule missing');
    assert.match(body, /--home-header-flank-w:\s*calc\(var\(--control-size\)\s*\*\s*2\s*\+\s*8px\)/,
        'header-menu.js permanently folds logoutBtn/settingsBtn into its '
        + 'overflow panel, leaving #configEditorBtn and the kebab as the '
        + 'only inline controls (the message archive icon that used to be '
        + 'a third was removed from the top bar entirely, issue #729, Joe '
        + 'ccsliinc, 2026-09-26). Guessing three buttons here once starved '
        + 'the title to a couple of characters at 390px.');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the launchpad-only second row does not touch .header\'s own padding/border', () => {
    const headerBody = ruleBody(styleRules, '.header');
    assert.ok(headerBody !== null, '.header rule missing');
    assert.ok(!/padding-top|padding-bottom/.test(headerBody),
        '.header must not gain new vertical padding for the home layout');
});

test('the subheader truncates rather than wraps, so it cannot grow the header on a phone', () => {
    const body = ruleBody(styleRules, '.home-subheader');
    assert.ok(body !== null, '.home-subheader rule missing');
    assert.match(body, /white-space:\s*nowrap\s*;/,
        'a wrapped second line would make the header taller than the block '
        + 'this change removed, on exactly the width that mattered most');
    assert.match(body, /text-overflow:\s*ellipsis\s*;/);
    assert.match(body, /text-align:\s*center\s*;/,
        'centred by real text-align against the header\'s own width, not a margin');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
