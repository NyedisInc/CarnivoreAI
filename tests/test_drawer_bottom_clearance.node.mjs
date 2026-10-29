// on the terminal screen

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const cssDir = path.join(__dirname, '..', 'client', 'css');

let failed = 0;
function test(name, fn) {
    try { fn(); console.log(`ok - ${name}`); }
    catch (err) { failed += 1; console.log(`not ok - ${name}\n  ${err.message}`); }
}

function css(name) {
    return fs.readFileSync(path.join(cssDir, name), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
}

function blocksFor(text, selector) {
    const out = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(text)) !== null) {
        const sels = m[1].split(',').map((s) => s.trim());
        if (sels.some((s) => s === selector || s.endsWith(' ' + selector))) out.push(m[2]);
    }
    return out;
}

function zIndex(text, selector) {
    for (const body of blocksFor(text, selector)) {
        const m = body.match(/z-index:\s*(\d+)/);
        if (m) return Number(m[1]);
    }
    return NaN;
}

const drawerSheets = fs.readdirSync(cssDir).filter((f) => /^session-sidebar.*\.css$/.test(f));

test('the drawer stylesheets exist to be checked', () => {
    assert.ok(drawerSheets.includes('session-sidebar.css'), 'session-sidebar.css not found');
    assert.ok(blocksFor(css('session-sidebar.css'), '.session-sidebar-bar-slot').length > 0,
        'no .session-sidebar-bar-slot rule found; the selector parser is looking at nothing');
});

test('(a) no rule pads the bottom of the bar slot', () => {
    for (const f of fs.readdirSync(cssDir).filter((n) => n.endsWith('.css'))) {
        for (const body of blocksFor(css(f), '.session-sidebar-bar-slot')) {
            assert.ok(!/padding(-bottom|-block(-end)?)?\s*:/.test(body),
                `${f}: .session-sidebar-bar-slot declares padding again: ${body.trim()}`);
        }
    }
});

test('(b) no drawer stylesheet reserves room with the floating-button tokens', () => {
    for (const f of drawerSheets) {
        assert.ok(!/var\(--fab-(size|edge)\)/.test(css(f)),
            `${f} uses --fab-size/--fab-edge; the drawer paints above the floating buttons`);
    }
});

test('(c) the home-indicator inset reaches the panel exactly once', () => {
    let count = 0;
    for (const f of drawerSheets) count += (css(f).match(/safe-area-inset-bottom/g) || []).length;
    const ios = blocksFor(css('ios-chrome.css'), '.session-sidebar-panel')
        .filter((b) => /padding-bottom:\s*env\(safe-area-inset-bottom\)/.test(b)).length;
    assert.equal(ios, 1, 'ios-chrome.css must pad .session-sidebar-panel by env(safe-area-inset-bottom)');
    assert.equal(count, 0, `drawer stylesheets restate safe-area-inset-bottom ${count} time(s)`);
});

test('(d) no floating button is left on the terminal screen', () => {
    for (const f of fs.readdirSync(cssDir).filter((n) => n.endsWith('.css'))) {
        assert.ok(!/\.fab-menu-btn\b/.test(css(f)), `${f} styles .fab-menu-btn again`);
    }
    const html = fs.readFileSync(path.join(__dirname, '..', 'client', 'index.html'), 'utf8')
        .replace(/<!--[\s\S]*?-->/g, '');
    assert.ok(!/fab-menu-btn|terminalToolsBtn/.test(html),
        'client/index.html carries a floating terminal button again');
});

if (failed) { console.log(`${failed} failed`); process.exit(1); }
