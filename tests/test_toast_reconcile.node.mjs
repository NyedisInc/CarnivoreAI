// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');

import { makeEnv, toast, cards, settle } from './lib_toast_dom_stub.mjs';

const tests = [];
/** Description: register one named case. Inputs: name, fn. Output: None. */
function test(name, fn) { tests.push([name, fn]); }

function pinClock(mgr) {
    const clock = { at: 1000 };
    mgr._now = () => clock.at;
    return clock;
}


test('NEGATIVE CONTROL: a card the server still lists is kept', async () => {
    const { container, mgr } = makeEnv();
    pinClock(mgr);
    const t = toast('PermissionRequest', 'needs your permission', 'Bash: ls', 'A');
    mgr.add(t);
    assert.equal(cards(container).length, 1, 'setup');

    const removed = mgr.reconcileOpen([t], { since: 5000 });
    await settle();
    assert.equal(removed, 0);
    assert.equal(cards(container).length, 1,
        'the control is blind unless a still-open card demonstrably survives '
        + 'the same call that removes a closed one');
});

test('a card the server no longer lists is removed', async () => {
    const { container, mgr } = makeEnv();
    pinClock(mgr);
    mgr.add(toast('PermissionRequest', 'needs your permission', 'Bash: ls', 'A'));
    assert.equal(cards(container).length, 1, 'setup');

    const removed = mgr.reconcileOpen([], { since: 5000 });
    await settle();
    assert.equal(removed, 1);
    assert.equal(cards(container).length, 0,
        'the server answered this toast because the user typed; the card is '
        + 'the only thing left claiming otherwise');
});

test('removal never acks - the server already closed the record', async () => {
    const { container, mgr, acked } = makeEnv();
    pinClock(mgr);
    mgr.add(toast('Notification', 'wants your attention', 'hi', 'A'));
    mgr.reconcileOpen([], { since: 5000 });
    await settle();
    assert.equal(cards(container).length, 0);
    assert.equal(acked.length, 0,
        'acking a record the server has already closed is a write with '
        + 'nothing to change, aimed at a session this browser may not be on');
});

test('only the sessions the server dropped lose their cards', async () => {
    const { container, mgr } = makeEnv();
    pinClock(mgr);
    const a = toast('PermissionRequest', 'needs your permission', null, 'A');
    const b = toast('Notification', 'wants your attention', 'read me', 'B');
    mgr.add(a);
    mgr.add(b);
    assert.equal(cards(container).length, 2, 'setup');

    const removed = mgr.reconcileOpen([b], { since: 5000 });
    await settle();
    assert.equal(removed, 1);
    const left = cards(container);
    assert.equal(left.length, 1);
    assert.equal(left[0].querySelector('.toast__title-text').textContent,
        'wants your attention',
        "typing into one session says nothing about what another is asking");
});


test('a card that arrived AFTER the snapshot was taken is spared', async () => {
    const { container, mgr } = makeEnv();
    const clock = pinClock(mgr);

    const requestedAt = 5000;
    clock.at = 5200;
    mgr.add(toast('PermissionRequest', 'needs your permission', 'Bash: rm', 'A'));
    assert.equal(cards(container).length, 1, 'setup');

    const removed = mgr.reconcileOpen([], { since: requestedAt });
    await settle();
    assert.equal(removed, 0);
    assert.equal(cards(container).length, 1,
        'a snapshot older than the card cannot testify about it; removing it '
        + 'would destroy a notification the server does hold');
});

test('the spared card is removed by the NEXT tick, once one can speak to it',
    async () => {
        const { container, mgr } = makeEnv();
        const clock = pinClock(mgr);
        clock.at = 5200;
        mgr.add(toast('PermissionRequest', 'needs your permission', null, 'A'));
        mgr.reconcileOpen([], { since: 5000 });
        await settle();
        assert.equal(cards(container).length, 1, 'setup: spared by the first tick');

        const removed = mgr.reconcileOpen([], { since: 15000 });
        await settle();
        assert.equal(removed, 1);
        assert.equal(cards(container).length, 0,
            'sparing must be a DELAY, never a permanent exemption, or the '
            + 'card never leaves at all');
    });

test('with no snapshot instant the set is taken as authoritative', async () => {
    const { container, mgr } = makeEnv();
    const clock = pinClock(mgr);
    clock.at = 9999;
    mgr.add(toast('Stop', 'Your turn', null, 'A'));
    const removed = mgr.reconcileOpen([]);
    await settle();
    assert.equal(removed, 1);
    assert.equal(cards(container).length, 0);
});


test('bare ids and server-shape objects are both understood', async () => {
    const { container, mgr } = makeEnv();
    pinClock(mgr);
    const t = toast('Stop', 'Your turn', null, 'A');
    mgr.add(t);
    assert.equal(mgr.reconcileOpen([t.id], { since: 5000 }), 0);
    await settle();
    assert.equal(cards(container).length, 1);
});

test('a malformed response removes nothing rather than clearing the screen',
    async () => {
        const { container, mgr } = makeEnv();
        pinClock(mgr);
        mgr.add(toast('PermissionRequest', 'needs your permission', null, 'A'));
        for (const bad of [null, undefined, 'nonsense', { toasts: [] }, 42]) {
            assert.equal(mgr.reconcileOpen(bad, { since: 5000 }), 0);
        }
        await settle();
        assert.equal(cards(container).length, 1,
            'a bad response is not evidence a notification was answered');
    });

test('reconciling twice removes once - it is idempotent', async () => {
    const { container, mgr } = makeEnv();
    pinClock(mgr);
    mgr.add(toast('Notification', 'wants your attention', 'x', 'A'));
    assert.equal(mgr.reconcileOpen([], { since: 5000 }), 1);
    await settle();
    assert.equal(mgr.reconcileOpen([], { since: 6000 }), 0);
    await settle();
    assert.equal(cards(container).length, 0);
});

test('a coalesced pile leaves the screen when every member is closed', async () => {
    const { container, mgr } = makeEnv();
    pinClock(mgr);
    for (let i = 0; i < 5; i++) mgr.add(toast('Stop', 'Your turn', `tail ${i}`, 'A'));
    assert.equal(cards(container).length, 1, 'setup: five Stops coalesce to one card');
    const removed = mgr.reconcileOpen([], { since: 5000 });
    await settle();
    assert.equal(removed, 5, 'every member id is its own record server-side');
    assert.equal(cards(container).length, 0);
});


test('NEGATIVE CONTROL: a local toast the server never issued survives, '
    + 'while a server toast in the SAME call is still swept', async () => {
    const { container, mgr } = makeEnv();
    pinClock(mgr);
    const local = {
        id: 'attach:s1:1:abc', session_id: 'A', session_name: null,
        kind: 'Attachment', title: 'attached', body: null,
        color: '#ff8800', acknowledged: false, local: true,
    };
    mgr.add(local);
    const server = toast('PermissionRequest', 'needs your permission', 'Bash: ls', 'A');
    mgr.add(server);
    assert.equal(cards(container).length, 2, 'setup');

    const removed = mgr.reconcileOpen([], { since: 5000 });
    await settle();
    assert.equal(removed, 1,
        'only the server-issued card may be counted as closed by a list '
        + 'the server actually issued ids for');
    assert.equal(mgr._byId.has(local.id), true,
        'the control is blind unless the local card demonstrably survives '
        + 'the very call that removes a server card beside it');
    assert.equal(mgr._byId.has(server.id), false,
        'a real server toast absent from the open list must still be '
        + 'swept, or the exemption has swallowed the whole sweep');
});

test('the exemption is not immortality: sending the prompt still retires it',
    async () => {
        const { mgr } = makeEnv();
        pinClock(mgr);
        const local = {
            id: 'attach:s1:2:def', session_id: 'A', session_name: null,
            kind: 'Attachment', title: 'attached', body: null,
            color: '#ff8800', acknowledged: false, local: true,
        };
        mgr.add(local);
        mgr.reconcileOpen([], { since: 5000 });
        assert.equal(mgr._byId.has(local.id), true, 'setup: survives the poll');
        assert.equal(mgr.dismissKindForSession(mgr.ATTACHMENT_KIND, 'A'), 1,
            'the real retirement path - the prompt being sent - must still '
            + 'work once the poll can no longer sweep this card');
        assert.equal(mgr._byId.has(local.id), false);
    });


test('the poller reconciles removals, against the RAW list, with an instant',
    () => {
        const src = fs.readFileSync(
            path.join(ROOT, 'client/js/toast-global-poll.js'), 'utf8');
        assert.match(src, /reconcileOpen\(list, \{ since: startedAt \}\)/,
            'removals must be computed from the raw server list, not the '
            + 'ring-filtered one: an id the ring suppresses is already gone '
            + 'from this browser, so subtracting it only makes the open set '
            + 'look smaller than the server said');
        assert.match(src, /var startedAt = Date\.now\(\);[\s\S]{0,400}getAllToasts/,
            'the instant must be stamped BEFORE the request leaves, or it '
            + 'describes the response rather than the snapshot');
        assert.match(src, /ToastManager\.backfill\(fresh\)/,
            'additions still go through the ring-filtered list');
    });

// ----------------------------------------------------------------- runner

let failed = 0;
for (const [name, fn] of tests) {
    try {
        // eslint-disable-next-line no-await-in-loop
        await fn();
        console.log('ok  ', name);
    } catch (err) {
        failed += 1;
        console.error('FAIL', name, '\n     ', err.message);
    }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
