
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
    Doc, ROOT, fakeStorage, loadModules, plain, repoFile, results, test,
} from './lib-sidebar-sessions.mjs';

const ARRANGEMENT_KEY = 'carnivore.session.sidebar.arrangement';

function loadStack(stored) {
    const storage = fakeStorage(stored === null ? {} : { [ARRANGEMENT_KEY]: stored });
    const { window } = loadModules([
        'status-led.js', 'session-status-summary.js',
        'session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js',
        'session-sidebar-search.js', 'session-sidebar-groups-search.js',
    ], { storage, document: new Doc() });
    return {
        A: window.SessionSidebarArrangement,
        storage,
    };
}

// =====================================================================
// =====================================================================

// =====================================================================
// =====================================================================

// =====================================================================
// =====================================================================

await test('the fold rides the SAME key as the pins and the order', () => {
    const { A, storage } = loadStack(null);
    A.load();
    A.save(['p'], ['p', 'a']);
    A.toggleCollapsed('pinned');
    const stored = JSON.parse(storage.map.get(ARRANGEMENT_KEY));
    assert.deepEqual(plain(stored.collapsed), ['pinned']);
    assert.deepEqual(plain(stored.pinned), ['p'], 'and the pins are still there');
    assert.equal(stored.v, 1, 'the version is NOT bumped for an additive optional field');
});

await test('a fold does NOT bump the version, or every stored arrangement dies', () => {
    const { A } = loadStack(JSON.stringify({ v: 1, pinned: ['p'], order: ['p', 'a'] }));
    const st = A.load();
    assert.equal(st.status, 'ok', 'an envelope with no collapsed key still parses');
    assert.deepEqual(plain(st.collapsed), [], 'and reads as nothing collapsed');
});

await test('a MALFORMED collapsed list is a preference miss, not an unreadable arrangement', () => {
    // there is nothing
    const { A } = loadStack(JSON.stringify({
        v: 1, pinned: ['p'], order: ['p', 'a'], collapsed: 'yes please',
    }));
    const st = A.load();
    assert.equal(st.status, 'ok', 'a bad fold must not condemn the whole arrangement');
    assert.deepEqual(plain(st.pinned), ['p'], 'the pins survive it');
    assert.deepEqual(plain(st.collapsed), []);
});

await test('an UNKNOWN section key is dropped, so no fold can become unreopenable', () => {
    const { A } = loadStack(JSON.stringify({
        v: 1, pinned: [], order: [], collapsed: ['pinned', 'archived'],
    }));
    assert.deepEqual(plain(A.load().collapsed), ['pinned']);
});

await test('toggling a section that does not exist changes nothing', () => {
    const { A } = loadStack(null);
    A.load();
    assert.equal(A.toggleCollapsed('nope'), false);
    assert.deepEqual(plain(A.current().collapsed), []);
});

await test('a reorder does not silently reopen a section the user folded', () => {
    const { A } = loadStack(null);
    A.load();
    A.save(['p'], ['p', 'a', 'b']);
    A.toggleCollapsed('other');
    A.move('a', 1, ['p', 'a', 'b']);
    assert.deepEqual(plain(A.current().collapsed), ['other'],
        'save() must pass the live folds through, not default them away');
});

// =====================================================================
// =====================================================================


await test('ITEM 66: the editor enforces the LABEL rule, not the old tmux-name rule', () => {
    const storage = fakeStorage();
    const { window } = loadModules(
        ['session-label.js'],
        { storage, document: new Doc() },
    );
    const R = { validateLabel: (raw) => window.SessionLabel.validate(raw) };

    for (const good of ['Media Compression', 'client: acme', 'v1.2 "final"', 'cost $5', 'ok']) {
        assert.equal(R.validateLabel(good).ok, true, `${good} must be a legal label`);
    }
    assert.equal(R.validateLabel('emoji \u{1F680} ok').ok, true);

    const trimmed = R.validateLabel('  Media Compression  ');
    assert.equal(trimmed.ok, true);
    assert.equal(trimmed.value, 'Media Compression');

    assert.equal(R.validateLabel('').ok, false, 'empty is refused');
    assert.equal(R.validateLabel('   ').ok, false, 'whitespace-only is refused');
    assert.equal(R.validateLabel(null).ok, false, 'null is refused');
    assert.equal(R.validateLabel('a\nb').ok, false, 'a newline is a control char');
    assert.equal(R.validateLabel('a\tb').ok, false, 'a tab is a control char');

    const max = window.SessionLabel.LABEL_MAX_CHARS;
    assert.equal(max, 200, 'the mirrored server limit');
    assert.equal(R.validateLabel('x'.repeat(65)).ok, true, '65 is fine for a label');
    assert.equal(R.validateLabel('x'.repeat(max)).ok, true, 'exactly the limit is fine');
    assert.equal(R.validateLabel('x'.repeat(max + 1)).ok, false, 'one over is refused');
});

// =====================================================================
// =====================================================================

await test('every file this round added stays under the 1000-line cap', () => {
    const files = [
        ['css', 'session-sidebar-groups.css'],
    ];
    for (const [dir, f] of files) {
        const lines = repoFile('client', dir, f).split('\n').length;
        assert.ok(lines <= 1000, `${f} is ${lines} lines, over the 1000 cap`);
    }
});

await test('nothing added this round uses an em-dash, an en-dash, or an emoji', () => {
    const files = [
        ['web', 'src', 'lib', 'drawer', 'rename.ts'],
        ['web', 'src', 'lib', 'drawer', 'store.ts'],
        ['web', 'src', 'lib', 'drawer', 'clicks.ts'],
        ['web', 'src', 'lib', 'drawer', 'chrome-clicks.ts'],
        ['client', 'css', 'session-sidebar-groups.css'],
    ];
    const EM = String.fromCharCode(8212);
    const EN = String.fromCharCode(8211);
    for (const parts of files) {
        const src = repoFile(...parts);
        assert.ok(!src.includes(EM), `${parts.join('/')} has an em-dash`);
        assert.ok(!src.includes(EN), `${parts.join('/')} has an en-dash`);
        assert.ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(src),
            `${parts.join('/')} has an emoji`);
    }
});

await test('every module this round added is actually SERVED', () => {
    const html = repoFile('client', 'index.html');
    assert.ok(html.includes('/static/dist/app.js'), 'the bundle is not served');
    assert.ok(html.includes('/static/css/session-sidebar-groups.css'),
        'the groups stylesheet is not linked');
});

await test('every class the groups module EMITS has a CSS rule somewhere', () => {
    const emitted = new Set();
    const emitters = [
        ['web', 'src', 'lib', 'drawer', 'rename.ts'],
        ...['BandSection.svelte', 'Heading.svelte', 'HeadingRenameEditor.svelte', 'SidebarList.svelte']
            .map((f) => ['web', 'src', 'lib', 'sidebar-shell', f]),
    ];
    for (const parts of emitters) {
        const src = repoFile(...parts);
        for (const m of src.matchAll(/class="([^"$]+)"/g)) {
            for (const c of m[1].split(/\s+/)) if (c.startsWith('session-sidebar')) emitted.add(c);
        }
    }
    assert.ok(emitted.size >= 6, `expected the group classes, found ${emitted.size}`);
    const css = repoFile('client', 'css', 'session-sidebar-groups.css')
        + repoFile('client', 'css', 'session-sidebar-density.css')
        + repoFile('client', 'css', 'session-sidebar.css')
        + repoFile('client', 'css', 'session-sidebar-rows.css')
        + repoFile('client', 'css', 'session-sidebar-band-structure.css');
    for (const c of emitted) {
        assert.ok(css.includes(`.${c}`), `${c} is emitted but has no CSS rule anywhere`);
    }
});

await test('the density contract is DECLARED in the stylesheet, not left to add up', () => {
    const css = repoFile('client', 'css', 'session-sidebar-density.css');
    for (const [mode, px] of [['compact', 24], ['cozy', 46], ['detailed', 66]]) {
        const re = new RegExp(
            `\\[data-density="${mode}"\\]\\s*\\.session-sidebar-row\\s*\\{[^}]*min-height:\\s*${px}px`);
        assert.ok(re.test(css), `${mode} must declare min-height: ${px}px`);
    }
});

// =====================================================================
// =====================================================================

await test('the deleted band-menu module is gone from the tree AND from index.html', () => {
    assert.ok(!fs.existsSync(path.join(ROOT, 'client', 'js', 'session-sidebar-band-menu.js')),
        'client/js/session-sidebar-band-menu.js must be deleted');
    const html = repoFile('client', 'index.html');
    assert.ok(!html.includes('session-sidebar-band-menu'),
        'index.html must not still load it');
});

await test('no stylesheet rule is left for the retired count', () => {
    const css = repoFile('client', 'css', 'session-sidebar-groups.css');
    assert.ok(!/\.session-sidebar-group__count\s*\{/.test(css), 'dead rule removed');
});

await test('the sidebar gutter is a dedicated shared token', () => {
    const tokens = repoFile('client', 'css', 'styles.css');
    assert.ok(tokens.includes('--sidebar-gutter:'), 'a dedicated token exists in styles.css');
    const gutterRule = repoFile('client', 'css', 'session-sidebar-groups.css')
        .match(/\.session-sidebar-group__gutter\s*\{([^}]*)\}/);
    assert.ok(gutterRule, 'the gutter class has a rule');
    assert.ok(/var\(--sidebar-gutter\)/.test(gutterRule[1]),
        'the gutter reads the shared token rather than a hardcoded width');
});

// =====================================================================
// =====================================================================

/**
 * Description: the (inner, outer) pair on one section header's summary
 *   LED. Scoped to that section's own slice of the markup so a two-group
 *   render cannot have one header's light read for another's.
 * Inputs: html (string) - a bodyHtml render. key (string) - band key.
 * Output: object|null - {inner, outer}, or null when no LED is present.
 */
function headerLed(html, key) {
    const start = html.indexOf(`data-group="${key}"`);
    if (start < 0) return null;
    const next = html.indexOf('data-group="', start + 1);
    const slice = html.slice(start, next < 0 ? html.length : next);
    const led = slice.indexOf('session-sidebar-group__project-led');
    if (led < 0) return null;
    const m = slice
        .slice(led)
        .match(/data-inner="([^"]+)" data-outer="([^"]+)"/);
    return m ? { inner: m[1], outer: m[2] } : null;
}

const { passes, failures } = results();
console.log(`${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
