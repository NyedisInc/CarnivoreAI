// ----------------------------------------------------------------------

import assert from 'node:assert/strict';

import { makeEnv, toast, cards, dismissAllRow } from './lib_toast_dom_stub.mjs';

const tests = [];
/** Description: register one named case. Inputs: name, fn. Output: None. */
function test(name, fn) { tests.push([name, fn]); }

function deferredRAF(sandbox) {
  const pending = [];
  sandbox.window.requestAnimationFrame = (fn) => { pending.push(fn); return pending.length; };
  return {
    flush() {
      const due = pending.splice(0);
      due.forEach((fn) => fn());
      return due.length;
    },
  };
}

function countRenders(mgr) {
  const state = { n: 0 };
  const original = mgr._render.bind(mgr);
  mgr._render = (...args) => { state.n += 1; return original(...args); };
  return { count: () => state.n };
}

function wait(ms) {
  return new Promise((resolve) => { setTimeout(resolve, ms); });
}


test('N toasts arriving in one burst produce ONE render pass, not N', async () => {
  const { container, mgr, sandbox } = makeEnv();
  const raf = deferredRAF(sandbox);
  const spy = countRenders(mgr);

  const RECORD_COUNT = 500;
  const toasts = [];
  for (let i = 0; i < RECORD_COUNT; i++) {
    toasts.push(toast('PermissionRequest', 'needs your permission', `Bash: cmd ${i}`, `session-${i}`));
  }
  mgr.backfill(toasts);

  assert.equal(spy.count(), 0,
    'nothing may render before the scheduled flush fires - a burst that '
    + 'rendered synchronously on every record is the exact defect being fixed');
  assert.equal(cards(container).length, 0, 'and nothing is on screen yet either');
  assert.equal(mgr._byId.size, RECORD_COUNT, 'the model already holds every record');

  const ran = raf.flush();
  assert.equal(ran, 1, 'exactly one frame callback was ever scheduled for this burst');
  assert.equal(spy.count(), 1,
    `${RECORD_COUNT} arrivals in one burst must collapse into ONE render pass`);
  assert.equal(cards(container).length, RECORD_COUNT,
    'every session still gets its own card once the batch flushes - '
    + 'batching must not drop a record');
});

test('a second burst after the first flush schedules its own single pass', async () => {
  const { container, mgr, sandbox } = makeEnv();
  const raf = deferredRAF(sandbox);
  const spy = countRenders(mgr);

  mgr.add(toast('PermissionRequest', 'needs your permission', null, 'a'));
  raf.flush();
  assert.equal(spy.count(), 1, 'setup: first burst flushed');

  for (let i = 0; i < 10; i++) {
    mgr.add(toast('PermissionRequest', 'needs your permission', `b${i}`, `s${i}`));
  }
  assert.equal(spy.count(), 1, 'the second burst must not render before its own flush');
  raf.flush();
  assert.equal(spy.count(), 2, 'the second burst gets exactly one render pass of its own');
  assert.equal(cards(container).length, 11);
});


test('dismissAll on a stack produces ONE render pass', async () => {
  const { container, mgr, sandbox } = makeEnv();
  const raf = deferredRAF(sandbox);
  const TOAST_COUNT = 50;
  for (let i = 0; i < TOAST_COUNT; i++) {
    mgr.add(toast('PermissionRequest', 'needs your permission', `b${i}`, `s${i}`));
  }
  raf.flush();
  assert.equal(cards(container).length, TOAST_COUNT, 'setup');

  const spy = countRenders(mgr);
  const dismissed = mgr.dismissAll();
  assert.equal(dismissed, TOAST_COUNT);
  assert.equal(spy.count(), 0, 'nothing renders synchronously from the click');

  await wait(220 + sandbox.window.ToastRenderBatch.FALLBACK_MS + 100);

  assert.equal(spy.count(), 1,
    `${TOAST_COUNT} simultaneous fade-out completions must collapse into `
    + 'ONE render pass, not one per card');
  assert.equal(cards(container).length, 0, 'every card is gone');
  assert.equal(dismissAllRow(container), null, 'and so is the control itself');
});


test('the batch still flushes when frames never fire (gotcha 9, hidden tab)',
  async () => {
    const { container, mgr, sandbox } = makeEnv();
    sandbox.window.requestAnimationFrame = () => {  };
    const spy = countRenders(mgr);

    for (let i = 0; i < 20; i++) {
      mgr.add(toast('PermissionRequest', 'needs your permission', `b${i}`, `s${i}`));
    }
    assert.equal(spy.count(), 0, 'setup: nothing rendered synchronously');

    await wait(sandbox.window.ToastRenderBatch.FALLBACK_MS + 100);

    assert.equal(spy.count(), 1,
      'a tab that never paints must still flush - delayed, never cancelled '
      + '(CLAUDE.md gotcha 9) - or a backfill received while backgrounded '
      + 'would never reach the screen at all');
    assert.equal(cards(container).length, 20);
  });

test(
  'NEGATIVE CONTROL: a bare-rAF-only scheduler (no timer fallback) never '
  + 'flushes in that same hidden tab - this is what gotcha 9 warns against',
  async () => {
    const { container, mgr, sandbox } = makeEnv();
    sandbox.window.requestAnimationFrame = () => {  };
    sandbox.window.ToastRenderBatch.schedule = (flush) => {
      sandbox.window.requestAnimationFrame(flush);
    };
    const spy = countRenders(mgr);

    mgr.add(toast('Stop', 'Your turn', null, 'a'));
    await wait(sandbox.window.ToastRenderBatch.FALLBACK_MS + 150);

    assert.equal(spy.count(), 0,
      'this is the failure mode being guarded against: with no timer race, '
      + 'a hidden tab holds the render forever. If this assertion ever '
      + 'fails, ToastRenderBatch.schedule has regressed toward this shape '
      + 'and the real fix above needs re-checking, not this test relaxing');
    assert.equal(cards(container).length, 0, 'the card never reaches the screen either');
  },
);


test('grouping, winner pick and the xn badge are unchanged under batching',
  async () => {
    const { container, mgr, sandbox } = makeEnv();
    const raf = deferredRAF(sandbox);

    for (let i = 0; i < 6; i++) mgr.add(toast('Stop', 'Your turn', `tail ${i}`, 'A'));
    mgr.add(toast('PermissionRequest', 'Allow Bash?', 'rm -rf /tmp/x', 'A'));
    raf.flush();

    const list = cards(container);
    assert.equal(list.length, 1, 'seven records for one session must still be one card');
    const card = list[0];
    assert.equal(card.dataset.kind, 'PermissionRequest',
      'the higher-severity member must still win the card');
    assert.equal(card.dataset.count, '7', 'the dismiss control must still count every record');
    const badge = card.querySelector('.toast__count');
    assert.equal(badge, null,
      'the xn badge counts the WINNER\'s kind, which occurs once here - it '
      + 'must not count the six Stops behind it');
  });


test('the attachment receipt still renders as its own card, batched or not',
  async () => {
    const { container, mgr, sandbox } = makeEnv();
    const raf = deferredRAF(sandbox);

    mgr.add(toast('Stop', 'Your turn', null, 'A'));
    mgr.add({
      id: 'att1', session_id: 'A', session_name: null, kind: mgr.ATTACHMENT_KIND,
      title: 'file.png', body: null, color: null, acknowledged: false, local: true,
    });
    raf.flush();

    const list = cards(container);
    assert.equal(list.length, 2,
      'the attachment receipt must keep its own card beside the session '
      + 'status card - COALESCE_KEY, not the render batch, decides that, '
      + 'and batching must not disturb it');
  });


test('a supersession reusing an id refreshes the card in place', async () => {
    const { container, mgr, sandbox } = makeEnv();
    const raf = deferredRAF(sandbox);
    mgr.add(toast('Stop', 'Your turn', 'first tail', 'A'));
    raf.flush();
    const held = cards(container)[0].dataset.toastId;
    const t = toast('Stop', 'Your turn', 'first tail', 'A');
    mgr.add({ ...t, id: held, body: 'second tail' });
    raf.flush();
    const list = cards(container);
    assert.equal(list.length, 1,
      'a supersession must refresh the held card, not add a second one');
    assert.equal(
      list[0].querySelector('.toast__body').textContent, 'second tail',
      'the card must carry the superseding record\'s body');
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
