
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');

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

function read(...parts) {
    return fs.readFileSync(path.join(root, ...parts), 'utf8');
}

function stripCssComments(text) {
    return text.replace(/\/\*[\s\S]*?\*\//g, '');
}

function mediaBlocks(sheet) {
    const out = [];
    const re = /@media\s*([^{]+)\{/g;
    let m;
    while ((m = re.exec(sheet))) {
        let depth = 1;
        let i = re.lastIndex;
        while (i < sheet.length && depth > 0) {
            if (sheet[i] === '{') depth++;
            else if (sheet[i] === '}') depth--;
            i++;
        }
        out.push({ cond: m[1].trim(), body: sheet.slice(re.lastIndex, i - 1) });
        re.lastIndex = i;
    }
    return out;
}

const headerActions = stripCssComments(read('client', 'css', 'header-actions.css'));
const sidebarCss = stripCssComments(read('client', 'css', 'session-sidebar.css'));
const topBar = read('web', 'src', 'opscenter', 'shell', 'TopBar.svelte');
const pinJs = read('web', 'src', 'lib', 'drawer', 'pin.ts');
const html = read('client', 'index.html');

const mobileMax = Number((pinJs.match(/export const MOBILE_MAX_PX = (\d+);/) || [])[1]);
const desktopMin = mobileMax + 1;

const HIDE_OPEN = /body:has\(\.session-sidebar-panel--open\)\s+#session-sidebar-toggle\s*\{([^}]*)\}/;

test('the docking breakpoint is read from web/src/lib/drawer/pin.ts', () => {
    assert.ok(Number.isInteger(mobileMax) && mobileMax > 0,
        'MOBILE_MAX_PX not found in web/src/lib/drawer/pin.ts');
});

test('desktop: the drawer toggle is hidden while the drawer is open', () => {
    const blocks = mediaBlocks(headerActions)
        .filter((b) => b.cond === `(min-width: ${desktopMin}px)`)
        .filter((b) => HIDE_OPEN.test(b.body));
    assert.equal(blocks.length, 1,
        `expected exactly one @media (min-width: ${desktopMin}px) rule hiding #session-sidebar-toggle while open`);
    const decls = blocks[0].body.match(HIDE_OPEN)[1];
    assert.match(decls, /visibility:\s*hidden;/);
    assert.match(decls, /pointer-events:\s*none;/);
    assert.doesNotMatch(decls, /display\s*:/,
        'display would collapse the header title elision budget; visibility keeps its box');
});

test('desktop: the rule sits beside #header-icon\'s, not in another file', () => {
    const iconAt = headerActions.indexOf('body:has(.session-sidebar-panel--open) #header-icon');
    const toggleAt = headerActions.search(HIDE_OPEN);
    assert.ok(iconAt >= 0 && toggleAt > iconAt, 'toggle rule must follow the #header-icon rule');
    assert.doesNotMatch(sidebarCss, /session-sidebar-panel--open\)\s+#session-sidebar-toggle/);
    const topBarStyle = (topBar.match(/<style>([\s\S]*)<\/style>/) || [, ''])[1];
    assert.doesNotMatch(topBarStyle, /session-sidebar-toggle/);
});

test('desktop: while closed nothing hides it (base rule is display: inline-flex)', () => {
    const unscoped = headerActions.replace(/@media[^{]+\{[\s\S]*?\n\}/g, '');
    assert.doesNotMatch(unscoped, /#session-sidebar-toggle\s*\{/,
        'the toggle must not be hidden outside the desktop media query');
});

test('phone: no rule at or below the breakpoint hides the drawer toggle', () => {
    for (const sheet of [headerActions, sidebarCss]) {
        for (const b of mediaBlocks(sheet)) {
            if (!/max-width/.test(b.cond)) continue;
            assert.doesNotMatch(b.body, /session-sidebar-toggle[^{]*\{[^}]*(visibility:\s*hidden|display:\s*none)/,
                `a phone media block (${b.cond}) hides the drawer toggle`);
        }
    }
});

test('phone: the toggle markup and its base styling are unchanged', () => {
    assert.ok(html.includes('id="session-sidebar-toggle"'));
    assert.match(sidebarCss, /\.session-sidebar-toggle\s*\{[^}]*display:\s*inline-flex;/);
});

test('the drawer\'s OWN wordmark carries no hide-while-open rule anywhere (the reverted fix)', () => {
    assert.doesNotMatch(headerActions, /#session-sidebar-brand\s*\{[^}]*visibility:\s*hidden/);
    assert.doesNotMatch(sidebarCss, /#session-sidebar-brand\s*\{[^}]*visibility:\s*hidden/);
    assert.doesNotMatch(topBar, /session-sidebar-brand/);
});

test('the sibling marks keep their hide-while-open rules at every width', () => {
    assert.match(headerActions,
        /(^|\n)body:has\(\.session-sidebar-panel--open\) #header-icon \{\s*visibility: hidden;\s*pointer-events: none;/);
    assert.match(topBar, /:global\(body:has\(\.session-sidebar-panel--open\)\) \.oc-topbar-word/);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
