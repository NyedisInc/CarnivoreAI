import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client/js/session-sidebar-chrome-clicks.js'), 'utf8');
const SIDEBAR = fs.readFileSync(path.join(ROOT, 'client/js/session-sidebar-clicks.js'), 'utf8');

let failed = 0;
function test(name, fn) {
    try { fn(); console.log(`ok - ${name}`); } catch (e) { failed++; console.log(`NOT OK - ${name}\n${e.stack}`); }
}

function load() {
    const calls = [];
    const window = {
        SessionSidebarArrangement: { toggleCollapsed: (k) => { calls.push(['fold', k]); return true; } },
        SessionSidebarBar: { run: (a) => calls.push(['bar', a]) },
    };
    const document = { getElementById: () => ({ textContent: '' }) };
    vm.runInNewContext(SRC, { window, document, console: { log() {} } });
    return { M: window.SessionSidebarChromeClicks, calls };
}

function click(selector, attrs = {}) {
    const el = { getAttribute: (n) => attrs[n] ?? null };
    let stopped = false;
    return {
        e: {
            target: { closest: (s) => (s === selector ? el : null) },
            stopPropagation: () => { stopped = true; },
        },
        stopped: () => stopped,
    };
}

const ctrl = { repaints: 0, repaint() { this.repaints++; } };

for (const [sel, attrs, want] of [
    ['[data-group-toggle]', { 'data-group-toggle': 'pinned' }, ['fold', 'pinned']],
]) {
    test(`${sel} is claimed, stopped and routed`, () => {
        const { M, calls } = load();
        const c = click(sel, attrs);
        assert.equal(M.claim(ctrl, c.e), true);
        assert.equal(c.stopped(), true, 'a claimed click must not reach the row switch');
        assert.deepEqual(calls, [want]);
    });
}


test('NEGATIVE: a click on a row is left for the row path', () => {
    const { M, calls } = load();
    const c = click('.session-sidebar-row');
    assert.equal(M.claim(ctrl, c.e), false);
    assert.equal(c.stopped(), false);
    assert.deepEqual(calls, []);
});

test('the ladder asks this module FIRST, before the drag claim', () => {
    const chrome = SIDEBAR.indexOf('SessionSidebarChromeClicks.claim(ctrl, e)');
    const drag = SIDEBAR.indexOf('SessionSidebarReorder.tookClick()');
    assert.ok(chrome > -1 && drag > -1, 'both claims must exist');
    assert.ok(chrome < drag, 'chrome is not a row; it is claimed ahead of every row-shaped handler');
});

if (failed) { console.log(`${failed} failed`); process.exit(1); }
