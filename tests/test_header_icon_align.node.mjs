// ---------------------------------------------------------------------------

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

function client(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', ...parts), 'utf8');
}

function ruleBody(sheet, selector) {
    const re = new RegExp(
        `(?:^|\\n)\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`
    );
    const m = sheet.match(re);
    assert.ok(m, `expected a rule for selector "${selector}"`);
    return m[1];
}

function stripCssComments(text) {
    return text.replace(/\/\*[\s\S]*?\*\//g, '');
}

const styles = client('css', 'styles.css');
const homeBar = client('css', 'home-bar.css');
const html = client('index.html');
// The screen-entry steps moved out of app.js into app-screen-entry.js.
const appJs = client('js', 'app.js') + client('js', 'app-screen-entry.js');


test('h1 pins a unitless line-height so both children get the same line box', () => {
    const body = stripCssComments(ruleBody(styles, '.header h1'));
    const m = body.match(/line-height:\s*([0-9.]+)\s*;/);
    assert.ok(m, 'h1 must declare a unitless line-height - it is what aligns the icon');
    assert.equal(m[1], '1.2', 'must be 1.2, matching .header-icon\'s 1.2em box height');
});

test('h1 keeps the flex centring the line-height depends on', () => {
    const body = stripCssComments(ruleBody(styles, '.header h1'));
    assert.match(body, /display:\s*flex/, 'h1 must stay a flex row');
    assert.match(body, /align-items:\s*center/, 'the boxes are centred by flex, not by line-height');
});

test('.header-icon declares no vertical-align', () => {
    const body = stripCssComments(ruleBody(styles, '.header-icon'));
    assert.doesNotMatch(
        body,
        /vertical-align/,
        'vertical-align does not apply to a flex item; it is inert here and misleads'
    );
});

test('.header-icon keeps the 1.2em box the line-height is matched to', () => {
    const body = stripCssComments(ruleBody(styles, '.header-icon'));
    assert.match(body, /width:\s*1\.2em/, 'icon box width');
    assert.match(body, /height:\s*1\.2em/, 'icon box height - h1 line-height 1.2 tracks this');
    assert.match(body, /flex-shrink:\s*0/, 'the marker must never be squeezed');
});


test('there is exactly one #statusText in the whole client', () => {
    const inHtml = (html.match(/id="statusText"/g) || []).length;
    assert.equal(inHtml, 1, 'the light is moved between screens, never cloned');
});

test('_placeStatusLight is wired for all three screens', () => {
    assert.match(appJs, /_placeStatusLight\(screen\)/, 'the function must exist');
    for (const screen of ['auth', 'launchpad', 'terminal']) {
        assert.match(
            appJs,
            new RegExp(`_placeStatusLight\\('${screen}'\\)`),
            `${screen} must place the light - a screen with no indicator is the bug`
        );
    }
});


test('#statusText is focusable so a tap can reveal its text', () => {
    const tag = html.match(/<span class="status" id="statusText"[^>]*>/);
    assert.ok(tag, 'expected the status span');
    assert.match(tag[0], /tabindex="0"/, 'a tap must be able to focus it - hover does not exist on a phone');
});

test('the light draws no CSS tooltip of its own (issue #981: no instant tooltips)', () => {
    assert.doesNotMatch(stripCssComments(styles), /\.status[^{,]*::after/,
        'an ::after bubble on the light shows instantly, beside nothing else that delays');
    assert.doesNotMatch(stripCssComments(homeBar), /\.status[^{,]*::after/,
        'nothing left to suppress in the bar');
});


test('the status group shrinks and the label ellipses', () => {
    const wrap = stripCssComments(ruleBody(homeBar, '.home-bar__status'));
    assert.match(wrap, /min-width:\s*0/, 'without it the full string sets the floor and overflows the bar');
    assert.match(wrap, /flex:\s*0 1 auto/, 'the group is the shrinkable item, the chip and bird are not');

    const label = stripCssComments(ruleBody(homeBar, '.home-bar__status-text'));
    assert.match(label, /overflow:\s*hidden/, 'clip rather than push the right-hand items off the edge');
    assert.match(label, /text-overflow:\s*ellipsis/, 'and say that it was clipped');
    assert.match(label, /white-space:\s*nowrap/, 'one line, in a 36px bar');
});

test('the dot keeps its shape while the label shrinks', () => {
    const body = stripCssComments(ruleBody(homeBar, '.home-bar__status .status'));
    assert.match(body, /flex-shrink:\s*0/, 'a squeezed 12px circle becomes an oval');
});

test('the status group is not a tap target and cannot grow the bar', () => {
    const wrap = stripCssComments(ruleBody(homeBar, '.home-bar__status'));
    assert.match(wrap, /height:\s*100%/, 'take the bar height, never set it');
    assert.doesNotMatch(wrap, /padding/, 'THIN IS THE POINT - the bar has no vertical padding anywhere');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
