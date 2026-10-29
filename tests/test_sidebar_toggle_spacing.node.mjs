
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

function ruleBody(sheet, selector) {
    const re = new RegExp(
        `(?:^|\\n)\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`
    );
    const m = sheet.match(re);
    assert.ok(m, `expected a rule for selector "${selector}"`);
    return m[1];
}

const styles = css('styles.css');
const sidebar = css('session-sidebar.css');
const iosChrome = css('ios-chrome.css');
const index = fs.readFileSync(
    path.join(__dirname, '..', 'client', 'index.html'), 'utf8'
);


test('the pinned drawer sets the dock offset token to the dock width', () => {
    const body = ruleBody(sidebar, 'body.session-sidebar-pinned');
    assert.match(body, /--dock-offset:\s*var\(--sidebar-dock-w\)\s*;/);
});

test('the header pays the dock offset PLUS the header side padding', () => {
    const body = ruleBody(iosChrome, '.header');
    assert.match(
        body,
        /padding-left:\s*calc\(\s*var\(--dock-offset,\s*0px\)\s*\+\s*var\(--header-pad-x\)/,
        'the docked header offset must be dock offset + --header-pad-x; paying '
        + 'the dock width alone puts the toggle flush against the panel border'
    );
});

test('the screen pays the bare dock offset', () => {
    const body = ruleBody(sidebar, '.screen');
    assert.match(body, /padding-left:\s*var\(--dock-offset,\s*0\)\s*;/);
});

test('the header and the screen do not share one offset rule', () => {
    assert.doesNotMatch(
        sidebar,
        /body\.session-sidebar-pinned \.header\s*,\s*\n?\s*body\.session-sidebar-pinned \.screen/,
        'the header and the screen need different offsets; do not re-merge'
    );
});

test('neither pinned offset restates the panel width as a literal', () => {
    assert.doesNotMatch(
        sidebar,
        /padding-left:\s*min\(/,
        'use --sidebar-dock-w, not a restated min() literal'
    );
});

test('the panel width and the dock offset come from the same token', () => {
    const panel = ruleBody(sidebar, '.session-sidebar-panel');
    assert.match(
        panel,
        /width:\s*var\(--sidebar-dock-w\)/,
        'the panel must be sized from --sidebar-dock-w so the two cannot drift'
    );
    assert.match(
        sidebar,
        /--sidebar-dock-w:\s*min\(320px,\s*85vw\)/,
        'expected --sidebar-dock-w defined once, as the panel width'
    );
});


test('--header-pad-x is defined at all three breakpoints', () => {
    for (const [value, where] of [
        ['20px', 'the base :root block'],
        ['15px', 'the max-width: 768px block'],
        ['12px', 'the max-width: 480px block'],
    ]) {
        assert.ok(
            styles.includes(`--header-pad-x: ${value}`),
            `expected --header-pad-x: ${value} in ${where}`
        );
    }
});

test('the header consumes --header-pad-x rather than a literal', () => {
    const body = ruleBody(styles, '.header');
    assert.match(
        body,
        /padding:\s*var\(--header-pad-y\)\s+var\(--header-pad-x\)/,
        'the header padding shorthand must use both tokens'
    );
});

test('styles.css no longer restates the header side padding per breakpoint', () => {
    assert.doesNotMatch(
        styles,
        /\.header\s*\{[^}]*padding-left:\s*\d+px/,
        'no literal padding-left on .header in styles.css'
    );
});


test('ios-chrome adds its insets on top of --header-pad-x', () => {
    const body = ruleBody(iosChrome, '.header');
    assert.match(
        body,
        /padding-left:\s*calc\(var\(--dock-offset,\s*0px\)\s*\+\s*var\(--header-pad-x\)\s*\+\s*env\(safe-area-inset-left\)\)/
    );
    assert.match(
        body,
        /padding-right:\s*calc\(var\(--header-pad-x\)\s*\+\s*env\(safe-area-inset-right\)\)/
    );
});

test('ios-chrome contains no literal header side padding at any breakpoint', () => {
    assert.doesNotMatch(
        iosChrome,
        /padding-(?:left|right):\s*calc\(\d+px\s*\+\s*env\(safe-area-inset-(?:left|right)\)\)/,
        'a literal here overrides --header-pad-x and re-opens the drift'
    );
});


test('the toggle is styled by a selector that actually matches it', () => {
    assert.match(
        index,
        /id="session-sidebar-toggle"[^>]*class="[^"]*session-sidebar-toggle/,
        'the toggle must carry the class its rule targets'
    );
    const body = ruleBody(sidebar, '.session-sidebar-toggle');
    assert.match(body, /width:\s*32px/);
    assert.match(body, /height:\s*32px/);
});

test('the toggle keeps its own left edge - no margin-left to fake the gap', () => {
    const body = ruleBody(sidebar, '.session-sidebar-toggle');
    assert.doesNotMatch(body, /margin-left:/);
    assert.match(body, /margin-right:\s*var\(--oc-space-1\)/);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
