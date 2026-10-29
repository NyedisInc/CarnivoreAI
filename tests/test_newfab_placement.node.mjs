
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

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

function ruleBodies(list, selector) {
    const out = [];
    for (const r of list) {
        const parts = r.selector.split(',').map((s) => s.trim());
        if (parts.includes(selector)) out.push(r.body);
    }
    return out;
}

function decl(body, prop) {
    const re = new RegExp('(?:^|;)\\s*' + prop + '\\s*:([^;]*)', 'i');
    const m = re.exec(body);
    return m ? m[1].replace(/!important/i, '').trim() : null;
}

const styles = read('client', 'css', 'styles.css');
const cssRules = rules(styles);
const indexHtml = read('client', 'index.html');
const anchorJs = read('client', 'js', 'anchor-popover.js');


function loadAnchorPopover(vw, vh) {
    const win = { innerWidth: vw, innerHeight: vh, visualViewport: null };
    const ctx = vm.createContext({ window: win, console: { log() {} } });
    vm.runInContext(anchorJs, ctx);
    return win.AnchorPopover;
}

function fakeEl(w, h) {
    return { offsetWidth: w, offsetHeight: h, style: {} };
}

function fakeAnchor(top, right, h) {
    const rect = { top, bottom: top + h, right, left: right - 36, height: h };
    return { getBoundingClientRect: () => rect };
}

test('place() flips ABOVE when the anchor sits low in the viewport', () => {
    const ap = loadAnchorPopover(1280, 800);
    const el = fakeEl(213, 318);
    const got = ap.place(el, fakeAnchor(683.9, 1022.5, 36));
    assert.ok(got.top + 318 <= 683.9,
        `menu bottom ${got.top + 318} must clear the trigger top 683.9; a `
        + 'menu that still hangs downward is the bug this file exists for');
    assert.ok(got.top >= 0 && got.top + 318 <= 800,
        `menu ${got.top}..${got.top + 318} must lie inside the 800px viewport`);
});

test('place() flips ABOVE at 390x844 too', () => {
    const ap = loadAnchorPopover(390, 844);
    const el = fakeEl(203, 308);
    const got = ap.place(el, fakeAnchor(719.6, 360, 34));
    assert.ok(got.top + 308 <= 719.6,
        `menu bottom ${got.top + 308} must clear the trigger top 719.6`);
    assert.ok(got.top >= 0 && got.top + 308 <= 844,
        `menu ${got.top}..${got.top + 308} must lie inside the 844px viewport`);
});

test('place() still drops BELOW when there is no room above', () => {
    const ap = loadAnchorPopover(1280, 800);
    const el = fakeEl(213, 318);
    const got = ap.place(el, fakeAnchor(70, 1022.5, 36));
    assert.ok(got.top >= 106,
        `with the anchor at 70..106 the menu must go below it, got ${got.top}`);
    assert.ok(got.top + 318 <= 800, 'and still be clamped into the viewport');
});

test('place() puts the menu right edge on the anchor right edge', () => {
    const ap = loadAnchorPopover(1280, 800);
    const el = fakeEl(213, 318);
    const got = ap.place(el, fakeAnchor(683.9, 1022.5, 36));
    assert.ok(Math.abs((got.left + 213) - 1022.5) <= 1,
        `menu right ${got.left + 213} must sit on the trigger right 1022.5`);
});


test('.new-fab__menu is position: fixed', () => {
    const bodies = ruleBodies(cssRules, '.new-fab__menu');
    assert.ok(bodies.length > 0, '.new-fab__menu must exist');
    assert.equal(decl(bodies[0], 'position'), 'fixed',
        'absolute leaves the menu a descendant of .launchpad-scroll, whose '
        + 'overflow-y: auto is what clipped it');
});

test('no .new-fab__menu rule declares a non-zero top', () => {
    for (const body of ruleBodies(cssRules, '.new-fab__menu')) {
        const top = decl(body, 'top');
        if (top === null) continue;
        assert.ok(/^0(px)?$/.test(top),
            `top: ${top} pins the menu below the trigger and defeats the `
            + 'flip; top is JS-owned now (Launchpad.placeNewFabMenu)');
    }
});

test('no .new-fab__menu rule declares right', () => {
    for (const body of ruleBodies(cssRules, '.new-fab__menu')) {
        assert.equal(decl(body, 'right'), null,
            'AnchorPopover writes left; a competing right would stretch the '
            + 'box and destroy the pills shared right edge');
    }
});


test('the pills still share a right edge', () => {
    const bodies = ruleBodies(cssRules, '.new-fab__menu');
    assert.equal(decl(bodies[0], 'align-items'), 'flex-end',
        'without this the pills stop sharing a right edge and the icon '
        + 'column goes ragged again');
});

test('the pill rows are still reversed', () => {
    const bodies = ruleBodies(cssRules, '.new-fab__item');
    assert.ok(bodies.length > 0, '.new-fab__item must exist');
    assert.equal(decl(bodies[0], 'flex-direction'), 'row-reverse',
        'row-reverse anchors each icon to the shared right edge; measured '
        + '0.0px spread across all six rows with it, ~58px without');
});

test('every pill row is 44px at every breakpoint', () => {
    const bodies = ruleBodies(cssRules, '.new-fab__item');
    assert.equal(decl(bodies[0], 'height'), '44px',
        '44px is the iOS/WCAG touch minimum for the launchpad primary '
        + 'actions');
    for (const body of bodies.slice(1)) {
        assert.equal(decl(body, 'height'), null,
            'a later rule (the 600px media query used to be one) must not '
            + 'shrink the touch target on the one device that is touched');
    }
});



test('no comment places the speed-dial in the recent projects heading', () => {
    for (const [name, src] of [
        ['index.html', indexHtml],
        ['styles.css', styles],
    ]) {
        const near = src.split('\n').filter((l, i, all) => {
            const window2 = all.slice(Math.max(0, i - 2), i + 3).join(' ');
            return /new-fab|speed-dial/i.test(window2)
                && /recent projects/i.test(l);
        });
        assert.equal(near.length, 0,
            `${name} still ties the speed-dial to "recent projects"; it is `
            + `in the "running sessions" heading row: ${near.join(' | ')}`);
    }
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
