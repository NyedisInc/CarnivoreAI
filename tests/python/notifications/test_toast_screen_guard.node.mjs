import assert from 'node:assert/strict';

import { makeEnv, toast, cards, settle } from '../../lib_toast_dom_stub.mjs';

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function typed(type, session) {
    const t = toast('Notification', 'hello', 'body', session);
    t.notify_type = type;
    return t;
}

test('NEGATIVE CONTROL: with no NotifyScreen the guard fails open and the card is drawn', async () => {
    const { container, mgr, sandbox } = makeEnv();
    assert.equal(sandbox.window.NotifyScreen, undefined);
    mgr.add(typed('session.finished', 's1'));
    await settle();
    assert.equal(cards(container).length, 1);
});

test('a type the filter hides draws no card and is not acknowledged', async () => {
    const { container, mgr, sandbox, acked } = makeEnv();
    const asked = [];
    sandbox.window.NotifyScreen = { shows: (t) => { asked.push(t.notify_type); return t.notify_type !== 'session.finished'; } };
    mgr.add(typed('session.finished', 's1'));
    await settle();
    assert.equal(cards(container).length, 0);
    assert.deepEqual(asked, ['session.finished']);
    assert.deepEqual(acked, []);
});

test('a type the filter shows is drawn; a toast with no notify_type is passed to the filter and drawn', async () => {
    const { container, mgr, sandbox } = makeEnv();
    sandbox.window.NotifyScreen = { shows: (t) => !(t.notify_type === 'session.finished') };
    mgr.add(typed('session.permission', 's1'));
    mgr.add(toast('Notification', 'plain', 'x', 's2'));
    await settle();
    assert.equal(cards(container).length, 2);
});

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
