// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

import { makeEnv, toast, cards, settle } from './lib_toast_dom_stub.mjs';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const MODE_SRC = fs.readFileSync(path.join(ROOT, 'client/js/toast-mode.js'), 'utf8');
const catalog = (await import(path.join(ROOT, 'client/js/i18n/catalog.en.js'))).default;

function t(key, params = {}) {
    let msg = catalog[key];
    if (msg === undefined) return key;
    if (typeof msg === 'object') msg = params.count === 1 ? msg.one : msg.other;
    return msg.replace(/\{(\w+)\}/g, (_, name) => String(params[name]));
}

function env(stored) {
    const base = makeEnv();
    const { sandbox } = base;
    const bridge = {
        value: stored,
        followers: [],
        read(field, local) { return field === 'toast_mode' && this.value !== undefined ? this.value : local(); },
        follow(field, apply) { this.followers.push(apply); return () => {}; },
    };
    sandbox.PreferenceBridge = bridge;
    const intervals = [];
    sandbox.setInterval = (fn) => { intervals.push(fn); return intervals.length; };
    sandbox.clearInterval = () => {};
    sandbox.CloudeI18n = { t };
    sandbox.ToastManager = sandbox.window.ToastManager;
    const gone = [];
    const go = (w) => { gone.push(w.session_id); return Promise.resolve(true); };
    sandbox.window.ToastNavigate = { go, open: go, isAskToast: () => false };
    vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js/i18n/tr.js'), 'utf8'), sandbox, { filename: 'tr.js' });
    vm.runInContext(MODE_SRC, sandbox, { filename: 'toast-mode.js' });
    assert.ok(sandbox.ToastMode, 'toast-mode.js did not export itself');
    return { ...base, gone, bridge, intervals };
}

function at(kind, title, session, seconds, detail = null) {
    const rec = toast(kind, title, null, session, 'cloude_' + session);
    rec.created_at = new Date(Date.UTC(2026, 8, 27, 12, 0, seconds)).toISOString();
    rec.detail = detail;
    return rec;
}

const PERMISSION = { reason: 'permission', tool: 'Bash', target: 'git push', snippet: 'pushing the branch' };
const FINISHED = { reason: 'turn_ended', snippet: 'the build is green' };

function pile() {
    return [
        at('Stop', 'Your turn', 'A', 1, { reason: 'turn_ended', snippet: 'first turn' }),
        at('PermissionRequest', 'needs your permission', 'A', 2, PERMISSION),
        at('Stop', 'Your turn', 'A', 3, FINISHED),
    ];
}

const text = (card, cls) => {
    const el = card._all([]).find((e) => e._classes().has(cls));
    return el ? el.textContent : null;
};

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('compact (absent setting): the most urgent event wins, generic title', async () => {
    const { container, mgr } = env(undefined);
    pile().forEach((r) => mgr.add(r));
    await settle();
    const shown = cards(container);
    assert.equal(shown.length, 1, 'one card per session in both modes');
    assert.equal(shown[0].dataset.kind, 'PermissionRequest', "Alex's fold keeps the permission");
    assert.equal(text(shown[0], 'toast__title-text'), 'needs your permission');
    assert.equal(shown[0].dataset.mode, 'compact');
});

test('detailed: the LATEST event wins, with its descriptive title and snippet', async () => {
    const { container, mgr } = env('detailed');
    pile().forEach((r) => mgr.add(r));
    await settle();
    const shown = cards(container);
    assert.equal(shown.length, 1);
    assert.equal(shown[0].dataset.kind, 'Stop', 'the newer event replaces the older');
    assert.equal(text(shown[0], 'toast__title-text'), 'finished and is waiting on you');
    assert.equal(text(shown[0], 'toast__body'), 'the build is green');
    assert.equal(text(shown[0], 'toast__count'), '×3', 'the stack counts every record behind it');
    assert.equal(text(shown[0], 'toast__session'), 'cloude_A', 'the session is named');
});

test('detailed: a permission card reads "wants permission: Bash git push"', async () => {
    const { container, mgr } = env('detailed');
    mgr.add(at('PermissionRequest', 'needs your permission', 'A', 2, PERMISSION));
    await settle();
    const card = cards(container)[0];
    assert.equal(text(card, 'toast__title-text'), 'wants permission: Bash git push');
    assert.equal(text(card, 'toast__body'), 'pushing the branch');
});

test('detailed: a record with no detail keeps its own title (never blank)', async () => {
    const { container, mgr } = env('detailed');
    mgr.add(at('Notification', 'wants your attention', 'A', 2, null));
    await settle();
    assert.equal(text(cards(container)[0], 'toast__title-text'), 'wants your attention');
});

test('detailed: a newer event arriving later replaces the card in place', async () => {
    const { container, mgr } = env('detailed');
    mgr.add(at('PermissionRequest', 'needs your permission', 'A', 2, PERMISSION));
    await settle();
    const before = cards(container)[0];
    mgr.add(at('Stop', 'Your turn', 'A', 9, FINISHED));
    await settle();
    const shown = cards(container);
    assert.equal(shown.length, 1);
    assert.equal(shown[0], before, 'the same card, updated, not a second one');
    assert.equal(text(shown[0], 'toast__title-text'), 'finished and is waiting on you');
});

test('detailed: two sessions waiting shows "2 sessions waiting"; compact does not', async () => {
    for (const [mode, expected] of [['detailed', '2 sessions waiting'], [undefined, null]]) {
        const { container, mgr } = env(mode);
        mgr.add(at('Stop', 'Your turn', 'A', 1, FINISHED));
        mgr.add(at('PermissionRequest', 'needs your permission', 'B', 2, PERMISSION));
        await settle();
        const row = container.childNodes.find((e) => e._classes().has('toast-waiting')) || null;
        assert.equal(row ? row.textContent : null, expected, `mode ${mode}`);
        assert.equal(cards(container).length, 2);
    }
});

test('detailed: one session waiting shows no aggregate line', async () => {
    const { container, mgr } = env('detailed');
    mgr.add(at('Stop', 'Your turn', 'A', 1, FINISHED));
    mgr.add(at('Stop', 'Your turn', 'A', 2, FINISHED));
    await settle();
    assert.equal(container.childNodes.filter((e) => e._classes().has('toast-waiting')).length, 0);
});

test('detailed: clicking a card opens that session and dismisses only that card', async () => {
    const { container, mgr, acked, gone } = env('detailed');
    const a = pile();
    a.forEach((r) => mgr.add(r));
    const b = at('PermissionRequest', 'needs your permission', 'B', 5, PERMISSION);
    mgr.add(b);
    await settle();
    const cardA = cards(container).find((c) => c.dataset.sessionId === 'A');
    cardA.click();
    await settle();
    assert.deepEqual(gone, ['A'], 'the click navigates to the session it names');
    assert.deepEqual([...acked].sort(), a.map((r) => r.id).sort(),
        "every record behind A's card is acked, and none of B's");
    const left = cards(container);
    assert.equal(left.length, 1);
    assert.equal(left[0].dataset.sessionId, 'B', "B's card is untouched");
});

test('compact: clicking a card navigates and acks nothing (unchanged)', async () => {
    const { container, mgr, acked, gone } = env(undefined);
    pile().forEach((r) => mgr.add(r));
    await settle();
    cards(container)[0].click();
    await settle();
    assert.deepEqual(gone, ['A']);
    assert.deepEqual(acked, [], "Alex's click reads a notification, it does not answer it");
    assert.equal(cards(container).length, 1);
});

test('a change to the setting on another device repaints the stack', async () => {
    const { container, mgr, bridge } = env(undefined);
    pile().forEach((r) => mgr.add(r));
    await settle();
    assert.equal(cards(container)[0].dataset.kind, 'PermissionRequest');
    assert.equal(bridge.followers.length, 1, 'toast-mode.js follows the field');
    bridge.value = 'detailed';
    bridge.followers[0]('detailed');
    await settle();
    assert.equal(cards(container)[0].dataset.kind, 'Stop');
    assert.equal(cards(container)[0].dataset.mode, 'detailed');
});

test('a card drawn before hydration repaints once the block is read', async () => {
    const { container, mgr, bridge, intervals, sandbox } = env(undefined);
    pile().forEach((r) => mgr.add(r));
    await settle();
    assert.equal(cards(container)[0].dataset.mode, 'compact', 'before hydration: compact');
    assert.equal(intervals.length, 1, 'toast-mode.js watches for the first hydration');
    bridge.value = 'detailed';
    intervals[0]();
    await settle();
    assert.equal(cards(container)[0].dataset.mode, 'compact',
        'NEGATIVE CONTROL: no repaint while the block is still unread');
    sandbox.Preferences = { HYDRATED: 'hydrated', status: () => 'hydrated' };
    intervals[0]();
    await settle();
    assert.equal(cards(container)[0].dataset.mode, 'detailed');
});

test('an unknown stored value reads compact', async () => {
    const { container, mgr } = env('loud');
    pile().forEach((r) => mgr.add(r));
    await settle();
    assert.equal(cards(container)[0].dataset.mode, 'compact');
});

test('detailed: a permission prompt is never hidden behind the overflow cap by a newer Stop in its session (u009-01)', async () => {
    const { container, mgr } = env('detailed');
    mgr.add(at('PermissionRequest', 'needs your permission', 'A', 1, PERMISSION));
    mgr.add(at('Stop', 'Your turn', 'A', 2, FINISHED));
    for (let i = 0; i < 12; i += 1) mgr.add(at('Stop', 'Your turn', 'Q' + i, 10 + i, FINISHED));
    await settle();
    const mine = cards(container).find((c) => text(c, 'toast__session') === 'cloude_A');
    assert.ok(mine, 'the session holding the permission prompt is still on screen');
    assert.equal(mine.attrs ? mine.attrs.role : mine.getAttribute('role'), 'alert', 'and it is announced as an alert');
});

let failed = 0;
for (const [name, fn] of tests) {
    try {
        await fn();
        console.log('ok   ' + name);
    } catch (err) {
        failed += 1;
        console.log('FAIL ' + name + '\n     ' + (err && err.stack || err));
    }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
if (failed) process.exit(1);
