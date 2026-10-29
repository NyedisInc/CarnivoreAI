
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

function js(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

function ruleBody(sheet, selector) {
    const re = new RegExp(
        `(?:^|\\n)\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`
    );
    const m = sheet.match(re);
    assert.ok(m, `expected a rule for selector "${selector}"`);
    return m[1];
}

function mediaBody(sheet, condition) {
    const idx = sheet.indexOf(`@media ${condition}`);
    assert.ok(idx !== -1, `expected an @media ${condition} block`);
    const open = sheet.indexOf('{', idx);
    let depth = 0;
    for (let i = open; i < sheet.length; i++) {
        if (sheet[i] === '{') depth++;
        else if (sheet[i] === '}') {
            depth--;
            if (depth === 0) return sheet.slice(open + 1, i);
        }
    }
    throw new Error(`unbalanced braces in @media ${condition}`);
}

const styles = css('styles.css');

function indexHtmlNoComments() {
    const raw = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8'
    );
    return raw.replace(/<!--[\s\S]*?-->/g, '');
}

const index = indexHtmlNoComments();


test('new-fab__item reverses the row so the icon sits on the shared right edge', () => {
    const body = ruleBody(styles, '.new-fab__item');
    assert.match(
        body,
        /flex-direction:\s*row-reverse/,
        'without row-reverse the icon leads the pill and its x tracks label length'
    );
});

test('new-fab__item puts its free padding on the LEFT (the ragged side)', () => {
    const body = ruleBody(styles, '.new-fab__item');
    const m = body.match(/padding:\s*([^;]+);/);
    assert.ok(m, 'expected a padding shorthand on .new-fab__item');
    const parts = m[1].trim().split(/\s+/);
    assert.equal(parts.length, 4, 'expected a 4-value padding shorthand');
    const [, right, , left] = parts;
    assert.equal(right, '0', 'right padding must be 0 so the icon can hug the shared edge');
    assert.notEqual(left, '0', 'the label side needs the breathing room');
});

test('new-fab__icon gaps on the right, the shared-edge side', () => {
    const body = ruleBody(styles, '.new-fab__icon');
    assert.match(body, /margin-right:/, 'the gap must be on the shared edge to keep icon x constant');
    assert.doesNotMatch(
        body,
        /margin-left:/,
        'a left margin here is the pre-fix layout and would offset the icon by label side'
    );
});

test('every FAB row is at least a 44px touch target at desktop', () => {
    const body = ruleBody(styles, '.new-fab__item');
    const m = body.match(/height:\s*(\d+)px/);
    assert.ok(m, 'expected an explicit height on .new-fab__item');
    assert.ok(
        Number(m[1]) >= 44,
        `FAB rows are primary launchpad actions; got ${m[1]}px, need >= 44px`
    );
});

test('the mobile media query does not shrink the FAB row below 44px', () => {
    const mobile = mediaBody(styles, '(max-width: 600px)');
    const m = mobile.match(/\.new-fab__item\s*\{([^}]*)\}/);
    assert.ok(m, 'expected a .new-fab__item rule inside the 600px block');
    const h = m[1].match(/height:\s*(\d+)px/);
    if (h) {
        assert.ok(
            Number(h[1]) >= 44,
            `phone target must not be smaller than desktop; got ${h[1]}px`
        );
    }
});

test('the FAB pill stays fully rounded at its new height', () => {
    const body = ruleBody(styles, '.new-fab__item');
    const h = Number(body.match(/height:\s*(\d+)px/)[1]);
    const r = body.match(/border-radius:\s*(\d+)px/);
    assert.ok(r, 'expected an explicit border-radius on .new-fab__item');
    assert.equal(
        Number(r[1]) * 2,
        h,
        'radius must be half the height or the pill renders as a slab'
    );
});


test('stroke-width for the marker lives ONLY in the markup, never in CSS', () => {
    const body = ruleBody(styles, '.adopt-disclosure__icon');
    assert.doesNotMatch(
        body,
        /stroke-width/,
        'stroke-width belongs on the svg element in launchpad.js, not here'
    );
});


test('the version chip carries no leftover header margin', () => {
    const body = ruleBody(styles, '.version');
    assert.ok(
        !/margin-left:/.test(body),
        'the chip moved to the home bar; a header margin must not survive the move'
    );
});

test('the header no longer renders the version chip', () => {
    const headerHits = index.match(/<span[^>]*class="[^"]*\bversion\b[^"]*"/g) || [];
    assert.equal(
        headerHits.length, 0,
        `the header still renders ${headerHits.length} version chip(s); it belongs to the bar now`
    );
});

test('the version chip still refuses to shrink', () => {
    const body = ruleBody(styles, '.version');
    assert.match(body, /flex-shrink:\s*0/, 'the chip must keep its width');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
