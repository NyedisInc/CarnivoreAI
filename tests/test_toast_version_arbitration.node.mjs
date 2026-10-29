
import assert from 'node:assert/strict';

import { makeEnv, toast, cards, settle } from './lib_toast_dom_stub.mjs';

const tests = [];
/** Description: register one named case. Inputs: name, fn. Output: None. */
function test(name, fn) { tests.push([name, fn]); }

function versioned(version, kind, title, body, session, sessionName, color) {
    const t = toast(kind, title, body, session, sessionName, color);
    if (version !== undefined) t.version = version;
    return t;
}


test('shouldReplace: a strictly higher version replaces', () => {
    const { sandbox } = makeEnv();
    assert.equal(
        sandbox.window.ToastVersionArbitration.shouldReplace({ version: 1 }, { version: 2 }),
        true);
});

test('shouldReplace: an equal version is a no-op', () => {
    const { sandbox } = makeEnv();
    assert.equal(
        sandbox.window.ToastVersionArbitration.shouldReplace({ version: 2 }, { version: 2 }),
        false);
});

test('shouldReplace: a lower version is discarded', () => {
    const { sandbox } = makeEnv();
    assert.equal(
        sandbox.window.ToastVersionArbitration.shouldReplace({ version: 3 }, { version: 2 }),
        false);
});

test('NEGATIVE CONTROL: a version missing on EITHER side always replaces, '
    + 'matching add()\'s pre-#39 behaviour exactly', () => {
    const { sandbox } = makeEnv();
    const M = sandbox.window.ToastVersionArbitration;
    assert.equal(M.shouldReplace({}, { version: 5 }), true,
        'a held record with no version carries no ordering information; '
        + 'refusing here would freeze a legacy card on its first content '
        + 'forever');
    assert.equal(M.shouldReplace({ version: 5 }, {}), true,
        'an incoming record with no version cannot be proven older, so it '
        + 'must still be applied - the pre-#39 behaviour');
    assert.equal(M.shouldReplace({}, {}), true);
    assert.equal(M.shouldReplace({ version: 5 }, { version: 2 }), false,
        'sanity: when BOTH sides carry real versions, ordinary comparison '
        + 'still applies - only a missing value gets the fallback');
});


test('add(): a higher-version delivery replaces the held record', async () => {
    const { container, mgr } = makeEnv();
    const first = versioned(1, 'Stop', 'Your turn', 'turn one');
    mgr.add(first);
    const second = versioned(2, 'Stop', 'Your turn', 'turn two');
    second.id = first.id;
    mgr.add(second);
    await settle();

    const c = cards(container);
    assert.equal(c.length, 1, 'still one card - a replace, not a second add');
    assert.ok(c[0].textContent.includes('turn two'),
        'the newer body must be what is on screen');
});

test('add(): a duplicated EQUAL-version delivery is a no-op', async () => {
    const { container, mgr } = makeEnv();
    const first = versioned(1, 'Stop', 'Your turn', 'turn one');
    mgr.add(first);
    const dup = versioned(1, 'Stop', 'Your turn', 'turn one');
    dup.id = first.id;
    mgr.add(dup);
    await settle();

    const c = cards(container);
    assert.equal(c.length, 1);
    assert.ok(c[0].textContent.includes('turn one'));
    assert.equal(mgr._byId.get(first.id), first,
        'an equal version must not overwrite the stored reference');
});

test('add(): a LOWER-version delivery is discarded, never regressing the card',
    async () => {
        const { container, mgr } = makeEnv();
        const newer = versioned(2, 'Stop', 'Your turn', 'turn two');
        mgr.add(newer);
        const stale = versioned(1, 'Stop', 'Your turn', 'turn one');
        stale.id = newer.id;
        mgr.add(stale);
        await settle();

        const c = cards(container);
        assert.equal(c.length, 1, 'no second card - the id is known');
        assert.ok(c[0].textContent.includes('turn two'),
            'the card must still show the newer content, never the stale '
            + 'redelivery');
        assert.equal(mgr._byId.get(newer.id).body, 'turn two');
    });

test('add(): three deliveries out of order (2, 1, 3) converge on the newest',
    async () => {
        const { mgr } = makeEnv();
        const id = 'shared-id';
        const mk = (v, body) => { const t = versioned(v, 'Stop', 'Your turn', body); t.id = id; return t; };
        mgr.add(mk(2, 'second'));
        mgr.add(mk(1, 'first'));
        mgr.add(mk(3, 'third'));
        await settle();
        assert.equal(mgr._byId.get(id).body, 'third');
        assert.equal(mgr._byId.get(id).version, 3);
    });

test('add(): a version missing on the incoming record still replaces '
    + '(a locally-minted or legacy toast keeps working)', async () => {
    const { container, mgr } = makeEnv();
    const first = versioned(1, 'Stop', 'Your turn', 'turn one');
    mgr.add(first);
    const noVersion = toast('Stop', 'Your turn', 'turn two');
    noVersion.id = first.id;
    mgr.add(noVersion);
    await settle();
    const c = cards(container);
    assert.ok(c[0].textContent.includes('turn two'),
        'today\'s (pre-#39) behaviour for a record with no version: always '
        + 'apply it');
});


test('a discarded stale delivery does not inflate the ×n badge or split '
    + 'into a second record', async () => {
    const { container, mgr } = makeEnv();
    const a = versioned(1, 'Stop', 'Your turn', 'a', 'ses_1');
    const b = versioned(1, 'Stop', 'Your turn', 'b', 'ses_1');
    mgr.add(a);
    mgr.add(b);
    const staleA = versioned(0, 'Stop', 'Your turn', 'stale-a', 'ses_1');
    staleA.id = a.id;
    mgr.add(staleA);
    await settle();

    assert.equal(mgr._byId.size, 2, 'still exactly two stored records');
    const c = cards(container);
    assert.equal(c.length, 1, 'one card - both Stops coalesce onto the session');
    const badge = c[0].querySelector('.toast__count');
    assert.equal(badge && badge.textContent, '×2',
        'the badge counts the two real records, unaffected by the '
        + 'discarded stale delivery');
});

test('dismiss-all still dismisses every record after a version-arbitrated '
    + 'update, never double-counting the replaced id', async () => {
    const { mgr } = makeEnv();
    const first = versioned(1, 'Notification', 'hi', 'v1', 'ses_1');
    mgr.add(first);
    const updated = versioned(2, 'Notification', 'hi', 'v2', 'ses_1');
    updated.id = first.id;
    mgr.add(updated);
    await settle();

    const n = mgr.dismissAll();
    assert.equal(n, 1, 'one stored record, one dismissal - not one per '
        + 'version this id ever carried');
});

// ------------------------------------------------------------------- run

let failed = 0;
for (const [name, fn] of tests) {
    try {
        await fn();
        console.log(`ok   ${name}`);
    } catch (err) {
        failed += 1;
        console.log(`FAIL ${name}\n     ${err && err.stack}`);
    }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
