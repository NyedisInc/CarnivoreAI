
import assert from 'node:assert/strict';
import vm from 'node:vm';

import { makeEnv, toast, cards, overflow, settle } from './lib_toast_dom_stub.mjs';

function ses(i) { return `ses_${i}`; }


const tests = [];
/** Description: register one named case. Inputs: name, fn. Output: None. */
function test(name, fn) { tests.push([name, fn]); }

test('a burst of identical Stops renders ONE card carrying an x<n> badge', () => {
    const { container, mgr } = makeEnv();
    for (let i = 0; i < 12; i++) mgr.add(toast('Stop', 'Your turn', `tail ${i}`));
    const c = cards(container);
    assert.equal(c.length, 1, 'twelve identical Stops must collapse to one card');
    const badge = c[0].querySelector('.toast__count');
    assert.ok(badge, 'the coalesced card must carry a count badge ELEMENT');
    assert.equal(badge.textContent, '×12');
    assert.equal(c[0].querySelector('.toast__title-text').textContent, 'Your turn');
    assert.equal(c[0].querySelector('.toast__body').textContent, 'tail 11');
    assert.equal(overflow(container), null, 'one card needs no overflow row');
});

test('two Notifications with DIFFERENT messages, ONE session, are one card', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Notification', 'Claude is waiting', 'needs a file path'));
    mgr.add(toast('Notification', 'Claude is waiting', 'idle for 60s'));
    const c = cards(container);
    assert.equal(c.length, 1, 'one session gets one card');
    assert.equal(c[0].querySelector('.toast__count').textContent, '×2');
    assert.equal(c[0].querySelector('.toast__body').textContent, 'idle for 60s',
        'the newest message is the one on the card');
});

test('two Notifications in DIFFERENT sessions stay two cards', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Notification', 'Claude is waiting', 'needs a file path', 'A'));
    mgr.add(toast('Notification', 'Claude is waiting', 'idle for 60s', 'B'));
    assert.equal(cards(container).length, 2,
        'the collapse is per session; two sessions are two things to deal with');
});

test('two identical Notifications DO coalesce', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Notification', 'Claude is waiting', 'idle for 60s'));
    mgr.add(toast('Notification', 'Claude is waiting', 'idle for 60s'));
    assert.equal(cards(container).length, 1);
});

test('two PermissionRequests for ONE session are one card, showing the newest', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: rm -rf build'));
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: curl example.com'));
    const c = cards(container);
    assert.equal(c.length, 1, 'one session, one card');
    assert.equal(c[0].querySelector('.toast__body').textContent, 'Bash: curl example.com',
        'the command shown must be the one Claude is actually blocked on');
    assert.equal(c[0].querySelector('.toast__count').textContent, '×2');
});

test('PermissionRequests in different sessions stay separate cards', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: rm -rf build', 'A'));
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: rm -rf build', 'B'));
    const c = cards(container);
    assert.equal(c.length, 2, 'two blocked sessions are two decisions to make');
    assert.equal(c[0].querySelector('.toast__count'), null, 'and neither carries a count');
});

test('THE BURST: 12 mixed toasts render a capped card set plus an accurate overflow row', () => {
    const { container, mgr } = makeEnv();
    for (let i = 0; i < 12; i++) {
        mgr.add(toast('Notification', 'Claude is waiting', `message ${i}`, ses(i)));
    }
    const c = cards(container);
    assert.equal(c.length, 3, 'the visible card count is capped at 3 on desktop');
    const ov = overflow(container);
    assert.ok(ov, 'and the 9 it is holding must be represented on screen');
    assert.equal(ov.getAttribute('data-hidden-count'), '9',
        'the row must state the TRUE number it is holding');
    assert.ok(ov.textContent.includes('+9 more'), `row read: ${ov.textContent}`);
    assert.ok(ov.textContent.includes('waiting on you'), `row read: ${ov.textContent}`);
    assert.equal(container.childNodes[container.childNodes.length - 1], ov);
});

test('expanding the overflow row renders every hidden card', () => {
    const { container, mgr } = makeEnv();
    for (let i = 0; i < 12; i++) mgr.add(toast('Notification', 'Claude is waiting', `m${i}`, ses(i)));
    assert.equal(cards(container).length, 3);
    overflow(container).click();
    assert.equal(cards(container).length, 12, 'nothing was dropped; it was held');
    assert.equal(overflow(container).textContent, 'show fewer');
});

test('a PermissionRequest is NEVER the thing behind the overflow row', () => {
    const { container, mgr } = makeEnv();
    for (let i = 0; i < 10; i++) mgr.add(toast('Notification', 'Claude is waiting', `m${i}`, ses(i)));
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: rm -rf /', ses(99)));
    const c = cards(container);
    assert.equal(c[0].getAttribute('data-kind'), 'PermissionRequest',
        'the blocking card sorts to the top');
    assert.equal(c[0].getAttribute('role'), 'alert',
        'and interrupts a screen reader rather than waiting politely');
    const ov = overflow(container);
    assert.equal(ov.getAttribute('data-worst-severity'), '2',
        'nothing above Notification may be in overflow');
});

test('every cap-exempt card renders even when there are more of them than the cap', () => {
    const { container, mgr } = makeEnv();
    for (let i = 0; i < 6; i++) mgr.add(toast('PermissionRequest', 'Permission needed', `cmd ${i}`, ses(i)));
    assert.equal(cards(container).length, 6,
        'the cap suppresses noise; six blocking prompts are not noise');
});

test('phone width caps lower and still tells the truth about the remainder', () => {
    const { container, mgr } = makeEnv(true);
    for (let i = 0; i < 8; i++) mgr.add(toast('Notification', 'Claude is waiting', `m${i}`, ses(i)));
    assert.equal(cards(container).length, 2, 'two cards on a phone, not three');
    assert.equal(overflow(container).getAttribute('data-hidden-count'), '6');
});

test('crossing the breakpoint re-renders rather than leaving a stale count', () => {
    const { container, mgr, mql } = makeEnv(false);
    for (let i = 0; i < 8; i++) mgr.add(toast('Notification', 'Claude is waiting', `m${i}`, ses(i)));
    assert.equal(cards(container).length, 3);
    mql.matches = true;
    for (const fn of mql._h) fn(mql);
    assert.equal(cards(container).length, 2);
    assert.equal(overflow(container).getAttribute('data-hidden-count'), '6');
});

test('dismissing a coalesced card acks EVERY member id, not just the visible one', async () => {
    const { container, mgr, acked } = makeEnv();
    const made = [];
    for (let i = 0; i < 5; i++) { const t = toast('Stop', 'Your turn', `tail ${i}`); made.push(t); mgr.add(t); }
    cards(container)[0].querySelector('.toast__dismiss').click();
    assert.deepEqual(acked.sort(), made.map((t) => t.id).sort(),
        'an unacked member would come straight back on the next attach backfill');
});

test('a toast the server already acked is never rendered', () => {
    const { container, mgr } = makeEnv();
    const t = toast('Stop', 'Your turn');
    t.acknowledged = true;
    mgr.add(t);
    assert.equal(cards(container).length, 0);
});

test('the id dedupe survives - backfill plus the WS race is still one card', () => {
    const { container, mgr } = makeEnv();
    const t = toast('Stop', 'Your turn', 'tail');
    mgr.add(t);
    mgr.add(t);
    assert.equal(cards(container).length, 1);
    assert.equal(cards(container)[0].querySelector('.toast__count'), null,
        'the same id twice is one event, not two - no count badge');
});

test('a superseded Stop - same id, newer body - refreshes the card in place', () => {
    const { container, mgr } = makeEnv();
    const first = toast('Stop', 'Your turn', 'turn one');
    mgr.add(first);
    mgr.add({ ...first, body: 'turn twelve' });

    const c = cards(container);
    assert.equal(c.length, 1, 'one server record must render as one card');
    assert.equal(c[0].querySelector('.toast__count'), null,
        'a single stored record must not render a count badge');
    assert.equal(c[0].querySelector('.toast__body').textContent, 'turn twelve',
        'the card must carry the newest body, not the first one');
});

test('a superseded Stop does not jump ahead of a newer Notification', () => {
    const { container, mgr } = makeEnv();
    const stop = toast('Stop', 'Your turn', 'one', 'A');
    mgr.add(stop);
    mgr.add(toast('Notification', 'Waiting', 'answer me', 'B'));
    mgr.add({ ...stop, body: 'two' });

    const c = cards(container);
    assert.equal(c.length, 2);
    assert.equal(c[0].querySelector('.toast__body').textContent, 'answer me',
        'the Notification arrived later and stays on top');
});

test('a toast arriving mid-fade does not resurrect the card being dismissed', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Stop', 'Your turn', 'first'));
    cards(container)[0].querySelector('.toast__dismiss').click();
    const fading = container.childNodes.filter(
        (e) => e._classes().has('toast') && e._classes().has('toast--dismissing'));
    assert.equal(fading.length, 1, 'the dismissed card should be animating out');
    mgr.add(toast('Stop', 'Your turn', 'second'));
    const live = container.childNodes.filter(
        (e) => e._classes().has('toast') && !e._classes().has('toast--dismissing'));
    assert.equal(live.length, 1, 'the arrival gets its OWN card');
    assert.notEqual(live[0], fading[0], 'and never the corpse of the dismissed one');
    assert.equal(live[0].querySelector('.toast__body').textContent, 'second');
    assert.equal(live[0].querySelector('.toast__count'), null,
        'one live toast is not a count of two');
});


test('two DIFFERENT kinds for one session render ONE card', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Stop', 'Your turn', 'turn ended'));
    mgr.add(toast('Notification', 'wants your attention', 'waiting for input'));
    const c = cards(container);
    assert.equal(c.length, 1, 'one session must never produce two cards');
    assert.equal(c[0].querySelector('.toast__title-text').textContent,
        'wants your attention',
        'the card shows the state that most warrants attention');
});

test('the card UPGRADES IN PLACE when a permission prompt arrives', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Stop', 'Your turn', 'turn ended'));
    const before = cards(container)[0];
    assert.equal(before.getAttribute('data-kind'), 'Stop');
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: rm -rf /'));
    const after = cards(container);
    assert.equal(after.length, 1, 'the upgrade must not open a second card');
    assert.equal(after[0], before,
        'and must happen on the SAME element, not by replacing it');
    assert.equal(after[0].getAttribute('data-kind'), 'PermissionRequest');
    assert.equal(after[0].getAttribute('role'), 'alert',
        'a blocking card interrupts a screen reader');
    assert.equal(after[0].querySelector('.toast__body').textContent, 'Bash: rm -rf /');
});

test('a lesser event NEVER takes the card off an unresolved higher one', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: rm -rf /'));
    for (let i = 0; i < 5; i++) mgr.add(toast('Stop', 'Your turn', `tail ${i}`));
    const c = cards(container);
    assert.equal(c.length, 1);
    assert.equal(c[0].getAttribute('data-kind'), 'PermissionRequest',
        'five later Stops must not downgrade a card the user is blocked on');
    assert.equal(c[0].getAttribute('data-severity'), '3',
        'and the card keeps the severity that makes it cap-exempt');
});

test('the badge counts the WINNING kind, not the session pile', () => {
    const { container, mgr } = makeEnv();
    for (let i = 0; i < 6; i++) mgr.add(toast('Stop', 'Your turn', `tail ${i}`));
    mgr.add(toast('PermissionRequest', 'Permission needed', 'Bash: ls'));
    const c = cards(container);
    assert.equal(c[0].querySelector('.toast__count'), null,
        'one permission prompt must not paint "Permission needed x7"');
    assert.equal(c[0].getAttribute('data-count'), '7',
        'the card still knows it is holding seven records');
    assert.match(c[0].querySelector('.toast__dismiss').getAttribute('aria-label'),
        /Dismiss 7 notifications/);
});

test('THE SAME EVENT TWICE does not double count and does not split the card', () => {
    const { container, mgr } = makeEnv();
    const stop = toast('Stop', 'Your turn', 'tail');
    const note = toast('Notification', 'wants your attention', 'look at me');
    mgr.add(stop);
    mgr.add(note);
    mgr.add(note);
    mgr.add(stop);
    const c = cards(container);
    assert.equal(c.length, 1);
    assert.equal(c[0].querySelector('.toast__count'), null,
        'one Notification delivered twice is one occurrence');
    assert.equal(c[0].getAttribute('data-count'), '2',
        'two records, not four');
});

test('dismissing the one card acks EVERY record of that session, of every kind', async () => {
    const { container, mgr, acked } = makeEnv();
    const made = [
        toast('Stop', 'Your turn', 'a'),
        toast('Notification', 'wants your attention', 'b'),
        toast('PermissionRequest', 'Permission needed', 'c'),
    ];
    for (const t of made) mgr.add(t);
    assert.equal(cards(container).length, 1, 'setup: one card');
    cards(container)[0].querySelector('.toast__dismiss').click();
    assert.deepEqual(acked.slice().sort(), made.map((t) => t.id).sort(),
        'a member left unacked comes straight back on the next attach backfill');
    await new Promise((r) => setTimeout(r, 300));
    assert.equal(cards(container).length, 0);
});

test('Dismiss all counts CARDS, and discloses only the blocking ones', () => {
    const { container, mgr } = makeEnv();
    for (let i = 0; i < 6; i++) mgr.add(toast('Stop', 'Your turn', `t${i}`, 'A'));
    mgr.add(toast('PermissionRequest', 'Permission needed', 'cmd', 'A'));
    mgr.add(toast('Notification', 'wants your attention', 'x', 'B'));
    const row = container.childNodes.find((e) => e._classes().has('toast-dismiss-all'));
    assert.equal(row.getAttribute('data-total'), '2',
        'two cards are on screen, so the control counts two');
    assert.equal(row.getAttribute('data-blocking'), '1',
        'six finished turns behind a permission prompt are not permission '
        + 'prompts; a disclosure that overstates is worse than none');
});

test('the attention order is READ from session-status-summary, never copied', () => {
    const { sandbox } = makeEnv();
    const fold = sandbox.SessionStatusSummary.SUMMARY_PRIORITY.map((e) => e.key);
    const buckets = sandbox.ToastSessionGroup.KIND_BUCKET;
    for (const kind of Object.keys(buckets)) {
        assert.ok(fold.includes(buckets[kind]),
            `${kind} maps to bucket ${buckets[kind]}, which the fold does not carry`);
    }
    assert.ok(fold.includes(sandbox.ToastSessionGroup.DEFAULT_BUCKET));
});

test('NEGATIVE CONTROL: with the fold gone, nothing is grouped by session', () => {
    const { container, mgr, sandbox } = makeEnv();
    vm.runInContext('delete globalThis.SessionStatusSummary;', sandbox);
    mgr.add(toast('Stop', 'Your turn', 'a'));
    mgr.add(toast('Notification', 'wants your attention', 'b'));
    assert.equal(cards(container).length, 2,
        'no attention order means no honest winner, so no card is merged');
});

test('the container is a polite live region', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Stop', 'Your turn'));
    assert.equal(container.getAttribute('aria-live'), 'polite');
});


test('the session name is a real control, and does NOT navigate on its own', () => {
    const { container, mgr, sandbox } = makeEnv();
    mgr.add(toast('Stop', 'Your turn', null, 'ses_1', 'cloude_myproject'));
    const calls = [];
    sandbox.window.SessionSidebar = {
        activateRow: (rowEl) => calls.push({ rowEl }),
    };
    const nameBtn = cards(container)[0].querySelector('.toast__session');
    assert.equal(nameBtn.tagName, 'BUTTON',
        'a session with somewhere to switch to must be a real, keyboard-activatable control');
    assert.equal(nameBtn.getAttribute('type'), 'button');
    nameBtn.click();
    assert.equal(calls.length, 0,
        'the name handler must no longer navigate: the card it sits inside '
        + 'already does, and two navigations from one click is the defect');
});

test('clicking the session name also dismisses the card', async () => {
    const { container, mgr, sandbox, acked } = makeEnv();
    const t = toast('Stop', 'Your turn', null, 'ses_1', 'cloude_myproject');
    mgr.add(t);
    sandbox.window.SessionSidebar = { activateRow: () => {} };
    const nameBtn = cards(container)[0].querySelector('.toast__session');
    nameBtn.click();
    await settle();
    assert.deepEqual(acked, [t.id], 'the click must ack the toast, same as the x button');
    assert.equal(cards(container).length, 0, 'the card must be gone after its name is clicked');
});

test('a toast with no session_name renders a plain, non-clickable name', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Stop', 'Your turn'));
    const nameEl = cards(container)[0].querySelector('.toast__session');
    assert.equal(nameEl.tagName, 'DIV',
        'nothing to navigate to must not render a control that does nothing on click');
});

test('the dismiss button still works, and does not also trigger the name switch', () => {
    const { container, mgr, sandbox, acked } = makeEnv();
    const t = toast('Stop', 'Your turn', null, 'ses_1', 'cloude_myproject');
    mgr.add(t);
    const calls = [];
    sandbox.window.SessionSidebar = { activateRow: (...args) => calls.push(args) };
    const card = cards(container)[0];
    card.querySelector('.toast__dismiss').click();
    assert.deepEqual(acked, [t.id], 'the dismiss must still ack the toast it belongs to');
    assert.equal(calls.length, 0, 'dismissing must never also fire the session switch');
});


test('two cards carry two different sessions\' accent colours', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Stop', 'Your turn', null, 'ses_1', null, '#d7788c'));
    mgr.add(toast('Stop', 'Your turn', null, 'ses_2', null, '#4fc1ff'));
    const accents = cards(container).map((c) => c._css['--toast-accent']).sort();
    assert.deepEqual(accents, ['#4fc1ff', '#d7788c'],
        'each card must carry its OWN session\'s colour, not a shared one');
});

test('a session with no baked colour leaves --toast-accent unset, which is the default-look case', () => {
    const { container, mgr } = makeEnv();
    const t = toast('Stop', 'Your turn');
    t.color = null;
    mgr.add(t);
    const card = cards(container)[0];
    assert.equal(card._css && card._css['--toast-accent'], undefined,
        'no inline override means the CSS fallback (today\'s look) applies, not an invented colour');
});

// ------------------------------------------------------------------- run

let failed = 0;
for (const [name, fn] of tests) {
    try {
        await fn();
        console.log(`ok   ${name}`);
    } catch (err) {
        failed += 1;
        console.log(`FAIL ${name}\n     ${err && err.message}`);
    }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
