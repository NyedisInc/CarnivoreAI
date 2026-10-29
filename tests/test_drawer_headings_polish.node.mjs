import assert from 'node:assert/strict';
import { Doc, fakeStorage, loadModules, repoFile, results, test } from './lib-sidebar-sessions.mjs';

function stack() {
    const { window } = loadModules([
        'status-led.js', 'session-status-summary.js',
        'session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js',
        'session-sidebar-group-membership.js', 'session-sidebar-group-store.js',
        'session-sidebar-search.js', 'session-sidebar-groups-search.js',
        'session-sidebar-fetch.js',
    ], { storage: fakeStorage({}), document: new Doc() });
    return window;
}

await test('a NEW running row carries the model, effort and tier the robot is drawn from', () => {
    const w = stack();
    const rows = [];
    w.SessionSidebarFetch.mergeLiveRow(rows, {
        tmux_session: 'cloude_new', session: { id: 'ses_1' }, activity_status: 'working',
        running_model: 'claude-opus-5-5', running_model_effort: 'high', running_model_tier: 4,
    });
    assert.equal(rows.length, 1, 'setup: the row was built');
    assert.equal(rows[0].running_model, 'claude-opus-5-5');
    assert.equal(rows[0].running_model_effort, 'high');
    assert.equal(rows[0].running_model_tier, 4);
});

await test('NEGATIVE: a payload with no model builds a row that says null, never a guess', () => {
    const w = stack();
    const rows = [];
    w.SessionSidebarFetch.mergeLiveRow(rows, { tmux_session: 'cloude_new', activity_status: 'idle' });
    assert.equal(rows[0].running_model, null);
    assert.equal(rows[0].running_model_tier, null);
});

await test('the layout list opens from the drawer button row, and the header copy stays hidden', () => {
    const css = repoFile('client', 'css', 'terminal-grid.css');
    assert.ok(!/#terminal-components \.oc-popover\s*\{/.test(css), 'no placement override');
    assert.ok(!/#headerComponentsBtn\s*\{\s*display:\s*flex/.test(css), 'nothing reveals the header button');
    assert.match(css, /#headerComponentsBtn\s*\{\s*display:\s*none;/, 'the header button is hidden');
    const bar = repoFile('web', 'src', 'lib', 'drawer', 'bar.ts');
    assert.ok(!/openTerminalComponents|'grid'/.test(bar), 'the bottom bar no longer owns the grid button');
});

await test('the bar is no longer drawn inside the list', () => {
    assert.ok(!/barHtml\(\)/.test(repoFile('web', 'src', 'lib', 'sidebar-shell', 'plan.ts')),
        'the list paint (inside the repainted list) must not draw the bar');
    assert.match(repoFile('client', 'index.html'), /id="session-sidebar-bar-slot"/);
});

await test('group headings are grey with no inter-group divider (owner, 2026-09-22: "change all the group headings back to the grey color they were originally and kill the HR between groups")', () => {
    const css = repoFile('client', 'css', 'session-sidebar-groups.css');
    assert.ok(!/\.session-sidebar-group \+ \.session-sidebar-group\s*\{[^}]*border-top/.test(css),
        'no hairline between groups');
    assert.match(css, /\.session-sidebar-group__header\s*\{[^}]*color:\s*var\(--oc-text-secondary\)/s,
        'headings are the same grey as before the colour experiments');
    assert.ok(!/\.session-sidebar-group__header--projects\s*\{[^}]*color:/s.test(css),
        'PROJECTS carries no colour override of its own, same as every other heading');
    const bands = repoFile('client', 'css', 'session-sidebar-band-structure.css');
    assert.match(bands,
        /\.session-sidebar-group\[data-group="pinned"\] \+ \.session-sidebar-group::before[^{]*\{[^}]*border-top/s,
        'pinned keeps its own separator now that the inter-group divider is gone');
    assert.ok(!/(^|[,}]\s*)\.session-sidebar-group \+ \.session-sidebar-group(::before)?\s*[,{]/m.test(bands),
        'the band dividers never fall between two hand-made groups');
});

const { passes, failures } = results();
console.log(`${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
