import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientJs = (f) => fs.readFileSync(
    path.join(__dirname, '..', 'client', 'js', f), 'utf8');
const clientCss = (f) => fs.readFileSync(
    path.join(__dirname, '..', 'client', 'css', f), 'utf8');

let passes = 0;
let failures = 0;
const queue = [];
const test = (name, fn) => queue.push([name, fn]);
async function runQueue() {
    for (const [name, fn] of queue) {
        try { await fn(); console.log(`ok - ${name}`); passes++; }
        catch (err) { console.log(`NOT OK - ${name}`); console.error(err); failures++; }
    }
}


function loadAnchorPopover() {
    const win = { visualViewport: null, innerWidth: 1000, innerHeight: 800 };
    win.window = win;
    const context = { window: win, globalThis: win, console: { log() {} } };
    vm.createContext(context);
    vm.runInContext(clientJs('anchor-popover.js'), context);
    return win;
}

function anchorAt(left, top, right, bottom) {
    return { getBoundingClientRect: () => ({ left, top, right, bottom }) };
}

function popover(w, h) {
    return { offsetWidth: w, offsetHeight: h, style: {} };
}

test('default: top-left corner of the panel lands at the bottom-left of the kebab', () => {
    const { AnchorPopover } = loadAnchorPopover();
    const anchor = anchorAt(100, 50, 130, 70);
    const el = popover(200, 300);
    const out = AnchorPopover.placeBelowLeft(el, anchor);
    assert.equal(out.left, 100, 'left must be the anchor\'s own left edge');
    assert.equal(out.top, 70, 'top must be the anchor\'s own bottom edge');
    assert.equal(el.style.left, '100px');
    assert.equal(el.style.top, '70px');
});

test('near the RIGHT edge: flips to hang off the anchor\'s right edge, growing left', () => {
    const { AnchorPopover } = loadAnchorPopover();
    const anchor = anchorAt(950, 50, 980, 70);
    const el = popover(200, 100);
    const out = AnchorPopover.placeBelowLeft(el, anchor);
    assert.equal(out.left, 780, 'must flip to anchor.right - width (980 - 200)');
    assert.equal(out.top, 70, 'the bottom edge is untouched by a right-edge flip');
});

test('near the BOTTOM edge: flips above the anchor, growing up', () => {
    const { AnchorPopover } = loadAnchorPopover();
    const anchor = anchorAt(50, 750, 80, 770);
    const el = popover(100, 200);
    const out = AnchorPopover.placeBelowLeft(el, anchor);
    assert.equal(out.left, 50, 'the left edge is untouched by a bottom-edge flip');
    assert.equal(out.top, 550, 'must flip to anchor.top - height (750 - 200)');
});

test('a corner case: the flip alone is not enough, and the final clamp still wins', () => {
    const { AnchorPopover } = loadAnchorPopover();
    const anchor = anchorAt(970, 770, 995, 795);
    const el = popover(300, 300);
    const out = AnchorPopover.placeBelowLeft(el, anchor);
    assert.equal(out.left, 692, 'clamped to the max reachable left (1000 - 300 - 8)');
    assert.equal(out.top, 470, 'the vertical flip alone was enough here (770 - 300)');
});

test('the shared place() (above, right-flush) is untouched by this addition', () => {
    const { AnchorPopover } = loadAnchorPopover();
    const anchor = anchorAt(400, 400, 430, 420);
    const el = popover(150, 60);
    const out = AnchorPopover.place(el, anchor);
    assert.equal(out.left, 280, 'right edges flush: anchor.right - width (430 - 150)');
    assert.equal(out.top, 332, 'above the anchor: anchor.top - height - MARGIN (400 - 60 - 8)');
});



function ruleBody(css, selector) {
    const re = new RegExp(`\\n\\s*${selector.replace(/[.[\]]/g, '\\$&')}\\s*\\{([^}]*)\\}`, 's');
    const m = css.match(re);
    return m ? m[1] : null;
}

function atBlock(css, prelude) {
    const i = css.indexOf(prelude);
    if (i < 0) return null;
    const open = css.indexOf('{', i);
    let depth = 0;
    for (let j = open; j < css.length; j++) {
        if (css[j] === '{') depth++;
        else if (css[j] === '}' && --depth === 0) return css.slice(open + 1, j);
    }
    return null;
}

function shadowLayers(value) {
    const out = [];
    let depth = 0, cur = '';
    for (const ch of value) {
        if (ch === '(') depth++;
        if (ch === ')') depth--;
        if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
}

function layerTokens(layer) {
    const out = [];
    let depth = 0, cur = '';
    for (const ch of layer) {
        if (ch === '(') depth++;
        if (ch === ')') depth--;
        if (/\s/.test(ch) && depth === 0) { if (cur) out.push(cur); cur = ''; } else cur += ch;
    }
    if (cur) out.push(cur);
    return out;
}

function maxPx(token) {
    const nums = [...token.matchAll(/(-?\d+(?:\.\d+)?)px/g)].map((m) => Math.abs(parseFloat(m[1])));
    return nums.length ? Math.max(...nums) : 0;
}

function shadowValues(fragment) {
    return [...fragment.matchAll(/box-shadow:\s*([^;]*);/g)].map((m) => m[1]);
}

const DROP_FAR = '0 8px 24px rgba(0, 0, 0, 0.55)';
const DROP_NEAR = '0 2px 6px rgba(0, 0, 0, 0.35)';

test('the panel ground is an opaque token clipped to the padding box over a top-down border', () => {
    const css = clientCss('popup-focus.css');
    const body = ruleBody(css, '.popup-focus');
    assert.ok(body, 'expected the .popup-focus rule');
    assert.match(body, /linear-gradient\(var\(--pf-ground\),\s*var\(--pf-ground\)\)\s+padding-box/,
        'the ground must be the flat opaque token, clipped to the padding box');
    assert.match(body, /linear-gradient\(to bottom,\s*var\(--pf-edge-top\),\s*var\(--pf-edge-bottom\)\)\s+border-box/,
        'the border must be a static top-to-bottom gradient, darker --oc-line-panel to brighter --oc-strip-edge, clipped to the border box');
    assert.match(body, /border:\s*1px solid transparent\s*;/, 'the border shows the gradient layer through');
    assert.doesNotMatch(body, /background-attachment:\s*local/,
        'local attachment would scroll the border with the items');
});

function conicGradientArgs(fragment) {
    const marker = 'conic-gradient(';
    const i = fragment.indexOf(marker);
    if (i < 0) return null;
    const start = i + marker.length;
    let depth = 1;
    let j = start;
    for (; j < fragment.length; j++) {
        if (fragment[j] === '(') depth++;
        else if (fragment[j] === ')') { depth--; if (depth === 0) break; }
    }
    return { args: fragment.slice(start, j), after: fragment.slice(j + 1, j + 40) };
}

test('a shimmer arc rides in its own conic-gradient border-box layer, on top of the static gradient', () => {
    const css = clientCss('popup-focus.css');
    const body = ruleBody(css, '.popup-focus');
    assert.ok(body, 'expected the .popup-focus rule');
    const conic = conicGradientArgs(body);
    assert.ok(conic, 'expected a conic-gradient for the shimmer layer');
    assert.match(conic.args, /^\s*from var\(--pf-angle\)/,
        'the shimmer must be a conic-gradient positioned by the registered angle');
    assert.match(conic.after, /^\s*border-box/,
        'the shimmer layer must be clipped to the border box, same as the static gradient underneath it');
    const stops = [...conic.args.matchAll(/(-?\d+(?:\.\d+)?)deg/g)].map((m) => parseFloat(m[1]));
    assert.ok(stops.length >= 4, 'expected at least a fade-in and fade-out stop pair');
    const span = Math.max(...stops) - Math.min(...stops);
    assert.ok(span > 0 && span <= 360, 'the stops must describe a real arc within one lap');
    const litSpanMatch = conic.args.match(/transparent\s+(-?\d+(?:\.\d+)?)deg,\s*var\(--pf-sheen\)[^,]*,\s*transparent\s+(-?\d+(?:\.\d+)?)deg/);
    assert.ok(litSpanMatch, 'expected transparent -> shimmer -> transparent stops around the lit centre');
    const litSpan = parseFloat(litSpanMatch[2]) - parseFloat(litSpanMatch[1]);
    assert.ok(litSpan >= 80 && litSpan <= 120, `expected a longer soft arc (80-120deg), got ${litSpan}deg of fade-in-to-fade-out`);
});

test('the shimmer travels: a registered angle, animated 6s linear infinite, distinct from the box-shadow', () => {
    const css = clientCss('popup-focus.css');
    const codeOnly = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const body = ruleBody(codeOnly, '.popup-focus');
    assert.ok(body, 'expected the .popup-focus rule to survive comment stripping');
    assert.match(body, /animation\s*:\s*popup-focus-orbit\s+6s\s+linear\s+infinite\s*;/,
        'the shimmer must run on a 6s linear infinite loop');
    assert.match(codeOnly, /@property\s+--pf-angle\s*\{[^}]*syntax:\s*'<angle>'[^}]*\}/s,
        'the angle must be registered as an <angle> so it interpolates smoothly');
    const keyframes = atBlock(codeOnly, '@keyframes popup-focus-orbit');
    assert.ok(keyframes, 'expected @keyframes popup-focus-orbit');
    assert.match(keyframes, /from\s*\{\s*--pf-angle:\s*0deg;?\s*\}/, 'the lap must start at 0deg');
    assert.match(keyframes, /to\s*\{\s*--pf-angle:\s*360deg;?\s*\}/, 'the lap must end at 360deg (same frame as the start)');
    assert.doesNotMatch(keyframes, /box-shadow/, 'the keyframes must only move the angle, never the box-shadow');
    assert.doesNotMatch(codeOnly, /@keyframes\s+srm-orbit\b/, 'the old orbit keyframes name must not resurface');
    assert.doesNotMatch(codeOnly, /@keyframes\s+session-row-menu-halo/, 'the breathing keyframes must stay gone');
    assert.doesNotMatch(codeOnly, /@supports\s*\(width:\s*calc\(1px \* sin\(1deg\)\)\)/,
        'the old trig-gated following glow must not resurface; the glow itself never animates');
});

test('reduced motion stops the animation and shows NO sheen, not a parked one', () => {
    const css = clientCss('popup-focus.css');
    const reduced = atBlock(css, '@media (prefers-reduced-motion: reduce)');
    assert.ok(reduced, 'expected a prefers-reduced-motion block');
    const rule = ruleBody(reduced, '.popup-focus');
    assert.ok(rule, 'expected the .popup-focus override inside the reduced-motion block');
    assert.match(rule, /animation\s*:\s*none\s*;/, 'reduced motion must turn the animation off');
    assert.match(rule, /--pf-sheen\s*:\s*transparent\s*;/,
        'a sheen frozen at 0deg is a bright stub on one spot of the border; reduced motion must clear it');
});

test('the sheen is brighter than both ends of the border, so it reads on every edge', () => {
    const body = ruleBody(clientCss('popup-focus.css'), '.popup-focus');
    const sheen = body.match(/--pf-sheen:\s*([^;]*);/);
    assert.ok(sheen, 'expected a --pf-sheen declaration');
    assert.match(sheen[1], /var\(--oc-text-bright\)/, 'the sheen must be lifted toward --oc-text-bright');
    assert.doesNotMatch(sheen[1], /--oc-strip-edge/, 'the sheen must not be the colour the border already ends in');
});

test('the kebab menu wears the shared class and draws no look of its own', () => {
    const driver = fs.readFileSync(path.join(__dirname, '..', 'web', 'src', 'lib', 'drawer-tabs', 'CascadeMenu.svelte'), 'utf8');
    assert.match(driver, /class="acm-menu popup-focus"/,
        'the kebab panel (the one menu driver since wrapper package S-6 part 2) must carry the shared popup-focus class');
    const own = clientCss('session-row-menu.css').replace(/\/\*[\s\S]*?\*\//g, '');
    const body = ruleBody(own, '.session-row-menu');
    assert.ok(body, 'expected the .session-row-menu rule');
    assert.doesNotMatch(body, /(^|\n)\s*(background|border|box-shadow|animation)\s*:/,
        'the look lives in popup-focus.css; the menu must not redraw it');
    assert.doesNotMatch(own, /@keyframes|@property/, 'no private keyframes or registered angle may remain');
});

test('NEGATIVE: the border is not a scrolling pseudo-element', () => {
    const css = clientCss('popup-focus.css');
    assert.doesNotMatch(css, /\.(popup-focus|session-row-menu)::(before|after)\s*\{/,
        'a pseudo-element ring scrolls with the content');
    const body = ruleBody(clientCss('session-row-menu.css'), '.session-row-menu');
    assert.match(body, /overflow-y:\s*auto/, 'the premise: the panel scrolls itself');
});

test('the coloured glow layer extends at most 5px (offset + blur + spread)', () => {
    const css = clientCss('popup-focus.css');
    const values = shadowValues(css.split('/* ---- One item')[0]);
    assert.equal(values.length, 1, `expected exactly one static box-shadow declaration; got ${values.length}`);
    let glows = 0;
    for (const v of values) {
        for (const layer of shadowLayers(v)) {
            if (/rgba\(0, 0, 0/.test(layer)) continue;
            glows++;
            const t = layerTokens(layer);
            const [x, y, blur, maybeSpread] = t;
            const spread = /px/.test(maybeSpread || '') ? maxPx(maybeSpread) : 0;
            const extent = Math.max(maxPx(x), maxPx(y)) + maxPx(blur) + spread;
            assert.ok(extent <= 5, `glow layer "${layer}" reaches ${extent}px, over 5px`);
        }
    }
    assert.ok(glows >= 1, `population check: expected at least 1 glow layer; got ${glows}`);
});

test('the box-shadow keeps both black drop shadows', () => {
    const css = clientCss('popup-focus.css');
    const values = shadowValues(css.split('/* ---- One item')[0]);
    assert.ok(values.length >= 1);
    for (const v of values) {
        assert.ok(v.includes(DROP_FAR), `missing far drop shadow in "${v}"`);
        assert.ok(v.includes(DROP_NEAR), `missing near drop shadow in "${v}"`);
    }
    assert.doesNotMatch(css, /@supports\s*\(width:\s*calc\(1px \* sin\(1deg\)\)\)/,
        'no trig-gated following glow should remain, nothing follows an angle any more');
});

test('the border and glow use theme tokens, never a literal hue', () => {
    const css = clientCss('popup-focus.css');
    const body = ruleBody(css, '.popup-focus');
    assert.match(body, /var\(--oc-strip-edge\)/);
    assert.match(body, /var\(--oc-orange\)/);
    const look = body.replace(/\/\*[\s\S]*?\*\//g, '');
    assert.doesNotMatch(look, /hsl\(/i, 'no literal hsl() hue (e.g. no hardcoded purple)');
    assert.doesNotMatch(look, /#[0-9a-fA-F]{3,8}\b/, 'no hex literal');
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
