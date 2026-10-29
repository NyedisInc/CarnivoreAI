
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

import { makeEnv, toast, cards, settle } from './lib_toast_dom_stub.mjs';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const NAVIGATE_SRC = fs.readFileSync(path.join(ROOT, 'client/js/toast-navigate.js'), 'utf8');

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function clickBubbling(el) {
    let stopped = false;
    const evt = {
        stopPropagation() { stopped = true; },
        preventDefault() {},
    };
    let node = el;
    while (node && !stopped) {
        const fns = (node._listeners && node._listeners.get('click')) || [];
        for (const fn of fns.slice()) fn(evt);
        node = node.parentNode;
    }
}

function sessionNameEl(card) {
    const el = card.querySelector('.toast__session');
    if (!el) {
        throw new Error(
            'no .toast__session inside the card, so this suite is clicking '
            + 'nothing - the class name changed and these assertions have '
            + 'stopped measuring the defect');
    }
    return el;
}

function makeNavEnv(activeTmuxName, rows) {
    const { sandbox, container, mgr } = makeEnv();
    const w = sandbox.window;

    const navigations = [];
    const listCalls = [];

    w.App = {
        returnToExistingTerminal(info) { navigations.push(info); },
    };
    w.API.listSessions = () => { listCalls.push(1); return Promise.resolve(rows); };
    w.SessionSidebar = {
        _activeSessionId: null,
        _activeTmuxName: activeTmuxName || null,
        activeTmuxName() { return this._activeTmuxName; },
    };
    const activateRowCalls = [];
    w.SessionSidebarClicks = {
        activateRow(ctrl, row) { activateRowCalls.push(row); },
    };

    vm.runInContext(NAVIGATE_SRC, sandbox, { filename: 'toast-navigate.js' });
    if (!w.ToastNavigate || typeof w.ToastNavigate.go !== 'function') {
        throw new Error(
            'toast-navigate.js did not export itself into the sandbox, so the '
            + 'card would bind no navigation at all and every count below '
            + 'would read zero for the wrong reason');
    }
    return { container, mgr, navigations, listCalls, activateRowCalls, w };
}

function row(sessionId, tmuxName) {
    return { tmux_session: tmuxName, session: { id: sessionId, name: tmuxName } };
}

function drain() { return new Promise((resolve) => setTimeout(resolve, 20)); }


test('NEGATIVE CONTROL: the card is on screen and its name is clickable', async () => {
    const { container, mgr } = makeNavEnv(null, [row('A', 'cloude_a')]);
    mgr.add(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    await settle();
    assert.equal(cards(container).length, 1,
        'the control is blind: a card must exist before any click assertion '
        + 'below means anything');
    const name = sessionNameEl(cards(container)[0]);
    assert.ok((name._listeners.get('click') || []).length > 0,
        'the name element must carry a click listener, or the bubbling test '
        + 'is measuring an inert node');
});

test('clicking the session name navigates EXACTLY ONCE', async () => {
    const { container, mgr, navigations, activateRowCalls } =
        makeNavEnv(null, [row('A', 'cloude_a')]);
    mgr.add(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    await settle();

    clickBubbling(sessionNameEl(cards(container)[0]));
    await drain();

    assert.equal(navigations.length, 1,
        'ONE click must produce ONE navigation. Two means the name handler '
        + 'and the card handler both ran, and each one closes the live '
        + 'WebSocket and opens another');
    assert.equal(activateRowCalls.length, 0,
        'the name handler must no longer reach SessionSidebarClicks.activateRow: '
        + 'that was the duplicate, and it ran with a fabricated controller '
        + 'whose null _activeTmuxName disabled the already-here guard');
});

test('clicking the card BODY navigates exactly once', async () => {
    const { container, mgr, navigations } = makeNavEnv(null, [row('A', 'cloude_a')]);
    mgr.add(toast('Stop', 'Your turn', 'some body text', 'A', 'cloude_a'));
    await settle();

    clickBubbling(cards(container)[0]);
    await drain();

    assert.equal(navigations.length, 1,
        'the card is still the thing that navigates, and once');
});

test('clicking the session name still dismisses the card', async () => {
    const { container, mgr } = makeNavEnv(null, [row('A', 'cloude_a')]);
    mgr.add(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    await settle();
    assert.equal(cards(container).length, 1, 'setup');

    clickBubbling(sessionNameEl(cards(container)[0]));
    await settle();

    assert.equal(cards(container).length, 0,
        'clicking the name dismisses the card: the user is being taken to '
        + 'the session it is about, so the card has served its purpose');
});


test('a toast for the session ALREADY attached does not navigate', async () => {
    const { container, mgr, navigations, w } =
        makeNavEnv(null, [row('A', 'cloude_a')]);
    mgr.add(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    await settle();
    assert.equal(cards(container).length, 1,
        'the card must be on screen before the click, or this case proves '
        + 'nothing at all');

    w.SessionSidebar._activeTmuxName = 'cloude_a';
    clickBubbling(cards(container)[0]);
    await drain();

    assert.equal(navigations.length, 0,
        're-entering the session already on screen closes a HEALTHY '
        + 'WebSocket and schedules a new one, which is the flicker this '
        + 'change exists to stop');
});

test('NEGATIVE CONTROL: a toast for a DIFFERENT session DOES navigate', async () => {
    const { container, mgr, navigations } =
        makeNavEnv('cloude_a', [row('A', 'cloude_a'), row('B', 'cloude_b')]);
    mgr.add(toast('Stop', 'Your turn', null, 'B', 'cloude_b'));
    await settle();

    clickBubbling(cards(container)[0]);
    await drain();

    assert.equal(navigations.length, 1,
        'THIS IS THE CASE A TOO-WIDE GUARD BREAKS. A guard that refused '
        + 'everything would pass every other test in this file and leave '
        + 'the user clicking notifications that do nothing');
    assert.equal(navigations[0].tmux_session, 'cloude_b',
        'and it must navigate to the session the toast names');
});

test('the already-attached guard still dismisses on a name click', async () => {
    const { container, mgr, navigations, w } =
        makeNavEnv(null, [row('A', 'cloude_a')]);
    mgr.add(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    await settle();
    assert.equal(cards(container).length, 1, 'setup');

    w.SessionSidebar._activeTmuxName = 'cloude_a';
    clickBubbling(sessionNameEl(cards(container)[0]));
    await settle();

    assert.equal(navigations.length, 0, 'no re-entry');
    assert.equal(cards(container).length, 0,
        'the dismiss must not be swallowed by the navigation guard: the '
        + 'user clicked the card, and a click that does nothing at all '
        + 'reads as broken');
});


function stubOpener(w, outcome) {
    const opened = [];
    w.CloudeWeb = { openApprovalFor(id) { opened.push(id); return Promise.resolve(outcome); } };
    return opened;
}

test('a PermissionRequest click opens the approvals popup, does NOT navigate, and dismisses the card', async () => {
    const { container, mgr, navigations, w } = makeNavEnv(null, [row('A', 'cloude_a')]);
    const opened = stubOpener(w, 'opened');
    mgr.add(toast('PermissionRequest', 'Needs you', 'run it?', 'A', 'cloude_a'));
    await settle();
    assert.equal(cards(container).length, 1, 'setup: the card must be on screen');

    clickBubbling(cards(container)[0]);
    await settle();

    assert.deepEqual(opened, ['A'], 'the popup opener gets the toast session, once');
    assert.equal(navigations.length, 0, 'a question never takes you to the terminal');
    assert.equal(cards(container).length, 0, 'the toast dismisses');
});

test('clicking the session NAME of a PermissionRequest also opens the popup exactly once', async () => {
    const { container, mgr, navigations, w } = makeNavEnv(null, [row('A', 'cloude_a')]);
    const opened = stubOpener(w, 'opened');
    mgr.add(toast('PermissionRequest', 'Needs you', null, 'A', 'cloude_a'));
    await settle();

    clickBubbling(sessionNameEl(cards(container)[0]));
    await settle();

    assert.equal(opened.length, 1, 'name handler plus card handler must not open twice');
    assert.equal(navigations.length, 0);
});

test('an ask whose list could not be read falls back to navigating', async () => {
    const { container, mgr, navigations, w } = makeNavEnv(null, [row('A', 'cloude_a')]);
    const opened = stubOpener(w, 'unknown');
    mgr.add(toast('PermissionRequest', 'Needs you', null, 'A', 'cloude_a'));
    await settle();

    clickBubbling(cards(container)[0]);
    await drain();

    assert.deepEqual(opened, ['A']);
    assert.equal(navigations.length, 1, 'unknown is not gone: the click must still land somewhere');
});

test('NEGATIVE CONTROL: Notification and Stop toasts still navigate and never call the opener', async () => {
    for (const kind of ['Notification', 'Stop']) {
        const { container, mgr, navigations, w } = makeNavEnv(null, [row('A', 'cloude_a')]);
        const opened = stubOpener(w, 'opened');
        mgr.add(toast(kind, 'Hello', null, 'A', 'cloude_a'));
        await settle();

        clickBubbling(cards(container)[0]);
        await drain();

        assert.equal(opened.length, 0, `${kind} must not open the popup`);
        assert.equal(navigations.length, 1, `${kind} still navigates`);
    }
});


test('the dismiss button dismisses WITHOUT navigating', async () => {
    const { container, mgr, navigations } =
        makeNavEnv(null, [row('A', 'cloude_a')]);
    mgr.add(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    await settle();

    const btn = cards(container)[0].querySelector('.toast__dismiss');
    assert.ok(btn, 'the dismiss control must exist');
    clickBubbling(btn);
    await settle();

    assert.equal(cards(container).length, 0, 'the card is gone');
    assert.equal(navigations.length, 0,
        'the dismiss button is a SIBLING of the name and stops propagation: '
        + 'throwing a notification away must never yank the user into the '
        + 'session it was about');
});


test('tmuxNameOf mirrors what returnToExistingTerminal reads', async () => {
    const { w } = makeNavEnv(null, []);
    const T = w.ToastNavigate;
    assert.equal(T.tmuxNameOf({ tmux_session: 'cloude_a' }), 'cloude_a',
        'the wrapper level wins, which is where /sessions/list puts it');
    assert.equal(T.tmuxNameOf({ session: { tmux_session: 'cloude_b' } }), 'cloude_b',
        'the nested level is the fallback for the flatter older shapes');
    assert.equal(T.tmuxNameOf({ name: 'cloude_c' }), 'cloude_c');
    assert.equal(T.tmuxNameOf({}), null,
        'a row with no derivable name answers null, which means NAVIGATE');
    assert.equal(T.tmuxNameOf(null), null);
});

test('alreadyAttachedTo refuses only on a positive match', async () => {
    const { w } = makeNavEnv('cloude_a', []);
    const T = w.ToastNavigate;
    assert.equal(T.alreadyAttachedTo('cloude_a'), true, 'the same name matches');
    assert.equal(T.alreadyAttachedTo('cloude_b'), false, 'a different name does not');
    assert.equal(T.alreadyAttachedTo(null), false,
        'an underivable name must NAVIGATE, not refuse');
    assert.equal(T.alreadyAttachedTo(''), false);

    w.SessionSidebar._activeTmuxName = null;
    assert.equal(T.alreadyAttachedTo('cloude_a'), false,
        'attached to nothing means navigate');

    delete w.SessionSidebar;
    assert.equal(T.alreadyAttachedTo('cloude_a'), false,
        'no sidebar at all means navigate: not having been able to ask is '
        + 'not evidence the user is already there');
});

test('a local card action runs once and retires the card; a card without one draws no button', async () => {
    const { container, mgr } = makeNavEnv(null, []);
    let ran = 0;
    mgr.add({ id: 'loc1', session_id: null, kind: 'WidgetsBars', title: 'added', body: null, local: true, action_label: 'undo', on_action() { ran += 1; } });
    mgr.add({ id: 'srv1', session_id: 's9', kind: 'Stop', title: 'done', body: null, action_label: 'undo', on_action() { ran += 100; } });
    await settle();
    const withAction = cards(container).find((c) => c.querySelector('.toast__action'));
    assert.ok(withAction, 'the local card draws its action');
    assert.equal(cards(container).filter((c) => c.querySelector('.toast__action')).length, 1, 'a server card draws none');
    clickBubbling(withAction.querySelector('.toast__action'));
    assert.equal(ran, 1, 'the action ran exactly once');
    await settle();
    assert.equal(cards(container).some((c) => c.dataset && c.dataset.toastId === 'loc1'), false, 'the card is retired');
});


let failed = 0;
for (const [name, fn] of tests) {
    try {
        await fn();
        console.log(`ok - ${name}`);
    } catch (err) {
        failed += 1;
        console.error(`not ok - ${name}\n    ${err && err.message}`);
    }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed === 0 ? 0 : 1);
