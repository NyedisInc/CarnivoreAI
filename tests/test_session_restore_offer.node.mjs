
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(__dirname, '..', 'client', 'js', 'session-restore-offer.js'), 'utf8');
const sandbox = { console, setTimeout, Date, globalThis: null };
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const M = sandbox.SessionRestoreOffer;

let failures = 0;
function test(name, fn) {
    try { fn(); console.log('PASS', name); } catch (err) { failures += 1; console.log('FAIL', name, err.message); }
}

test('only a reboot says restart', () => {
    assert.match(M.headline('reboot', 3, '9:05 pm'), /^3 sessions were open before the restart at 9:05 pm\. reopen them\?$/);
    for (const r of ['tmux_server_gone', 'sessions_gone', 'unknown_boot']) {
        assert.doesNotMatch(M.headline(r, 2, 'x'), /restart/, r);
    }
    assert.match(M.headline('tmux_server_gone', 1, ''), /^1 session was open before the terminal server stopped\. reopen them\?$/);
});

test('copy is lowercase and carries no dashes or emoji', () => {
    for (const r of ['reboot', 'tmux_server_gone', 'sessions_gone', 'unknown_boot']) {
        const h = M.headline(r, 4, 'sep 23, 9:05 pm');
        assert.equal(h, h.toLowerCase());
        assert.doesNotMatch(h, /[\u2013\u2014]/);
    }
});

test('a blocked row is never sent, even if its box is ticked', () => {
    const items = [
        { session_uuid: 'A', selectable: true, wrapper_default: 'claude-chrome' },
        { session_uuid: 'B', selectable: false, blocked: 'already_running_elsewhere', wrapper_default: 'claude-chrome' },
    ];
    const out = M.selection(items, { A: true, B: true }, { A: 'claude-skip-permissions' });
    assert.deepEqual(JSON.parse(JSON.stringify(out)), [{ session_uuid: 'A', agent_type: 'claude-skip-permissions' }]);
    assert.equal(M.blockedWords(items[1]), 'already running elsewhere');
    assert.equal(M.blockedWords(items[0]), '');
});

test('the default wrapper is used when none was changed', () => {
    const out = M.selection([{ session_uuid: 'A', selectable: true, wrapper_default: 'claude-chrome' }], { A: true }, {});
    assert.equal(out[0].agent_type, 'claude-chrome');
});

test('a wrapper that drops a flag says which', () => {
    const item = { wrapper_drops: { 'claude-skip-permissions': ['--chrome'], 'claude-chrome': [] } };
    assert.equal(M.dropWords(item, 'claude-skip-permissions'), 'comes back without --chrome');
    assert.equal(M.dropWords(item, 'claude-chrome'), '');
});

test('a conversation that disagrees with the record shows both', () => {
    assert.equal(M.conversationWords({ conversation: '4ac1ad63-aaaa', conversation_recorded: '02eacc04-bbbb' }),
        '4ac1ad63 (record says 02eacc04)');
    assert.equal(M.conversationWords({ conversation: null }), 'none recorded');
});

test('the headline time is the boot time for a reboot', () => {
    const t = M.headlineTime({ reason: 'reboot', boot_epoch: 1790200000, created_at: '2026-01-01T00:00:00Z' },
        (d) => String(d.getTime()));
    assert.equal(t, '1790200000000');
});

test('the panel escapes what it shows', () => {
    const html = M.panelHtml({ id: 'x', reason: 'reboot' },
        [{ session_uuid: 'A', selectable: true, title: '<b>x</b>', folder: '/a/b', wrapper_options: [] }], 0, () => 'now');
    assert.doesNotMatch(html, /<b>x<\/b>/);
    assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
});

test('ago reads in plain words', () => {
    const now = Date.parse('2026-09-23T12:00:00Z');
    assert.equal(M.ago('2026-09-23T11:59:30Z', now), 'just now');
    assert.equal(M.ago('2026-09-23T09:00:00Z', now), '3 hours ago');
    assert.equal(M.ago(null, now), 'unknown');
});

test('every selectable row starts ticked, however long it sat idle', () => {
    const idle = { session_uuid: 'I', selectable: true, last_work_at: '2026-09-05T00:00:00Z', folder: '/a', wrapper_options: [] };
    const blocked = { session_uuid: 'B', selectable: false, folder: '/a', wrapper_options: [] };
    assert.equal(M.initialChecked(idle), true);
    assert.equal(M.initialChecked(blocked), false);
    const html = M.panelHtml({ id: 'x', reason: 'reboot' }, [idle, blocked], 0, () => 'now');
    assert.match(html, /id="restore-offer-I" checked>/);
    assert.match(html, /id="restore-offer-B" disabled>/);
    assert.match(html, /select all \(1\)/);
});

test('a folded offer counts its new loss apart from the older rows', () => {
    const items = [{ lost_reason: 'tmux_server_gone' }, { lost_reason: 'tmux_server_gone' }, { lost_reason: 'sessions_gone' }];
    const c = M.headlineCounts('tmux_server_gone', items);
    assert.deepEqual({ ...c }, { current: 2, older: 1 });
    assert.equal(M.headline('tmux_server_gone', c.current, '', c.older),
        '2 sessions were open before the terminal server stopped, plus 1 older. reopen them?');
    assert.deepEqual({ ...M.headlineCounts('reboot', [{}]) }, { current: 1, older: 0 });
});

test('the trust note speaks only for a measured will_ask', () => {
    assert.equal(M.trustWords({ folder_trust: 'will_ask' }), 'claude will ask to trust this folder');
    assert.equal(M.trustWords({ folder_trust: 'trusted' }), '');
    assert.equal(M.trustWords({ folder_trust: 'unknown' }), '', 'not having looked is not a claim');
});

test('a reopen parked on the trust prompt is not reported as plain reopened', () => {
    const waiting = { outcome: 'reopened', startup_gate: 'awaiting_startup_prompt',
        detail: 'reopened - waiting on the folder trust prompt: open it and choose "Yes, I trust this folder"' };
    const plain = { outcome: 'reopened', detail: 'ok' };
    assert.match(M.resultWords(waiting), /waiting on the folder trust prompt/);
    assert.equal(M.resultWords(plain), 'reopened');
    assert.equal(M.summaryWords([waiting, plain, { outcome: 'refused' }]),
        '2 of 3 reopened, 1 waiting on the folder trust prompt');
    assert.equal(M.summaryWords([plain]), '1 of 1 reopened');
});

const { default: CATALOG } = await import('../client/js/i18n/catalog.en.js');
const { formatEntry } = await import('../client/js/i18n/format.js');
sandbox.CloudeI18n = { t: (key, params) => (key in CATALOG ? formatEntry(CATALOG[key], params, 'en') : key) };

test('each row goes queued, restoring, then opened or failed with the reason', () => {
    const s = M.progressStart([{ session_uuid: 'A' }, { session_uuid: 'B' }, { session_uuid: 'C' }]);
    assert.equal(M.progressHeader(s), 'restoring 1 of 3');
    assert.equal(M.progressWords(s.rows.A), 'queued');
    const f = (fields) => ({ type: 'restore_offer.progress', offer_id: 'o1', ...fields });
    assert.equal(M.applyProgress(s, 'o1', f({ session_uuid: 'A', phase: 'restoring' })), true);
    assert.equal(M.progressWords(s.rows.A), 'restoring...');
    assert.equal(M.applyProgress(s, 'o1', { ...f({ session_uuid: 'B', phase: 'restoring' }), offer_id: 'o2' }), false);
    assert.equal(M.applyProgress(s, 'o1', f({ session_uuid: 'Z', phase: 'restoring' })), false);
    assert.equal(M.applyProgress(s, 'o1', { type: 'sessions.changed', offer_id: 'o1', session_uuid: 'B' }), false);
    M.applyProgress(s, 'o1', f({ session_uuid: 'A', phase: 'done', outcome: 'reopened' }));
    M.applyProgress(s, 'o1', f({ session_uuid: 'B', phase: 'done', outcome: 'failed',
        detail: 'agent failed to launch: /bin/zsh: no such option: name' }));
    assert.equal(M.progressWords(s.rows.A), 'opened');
    assert.equal(M.progressWords(s.rows.B), 'failed: agent failed to launch: /bin/zsh: no such option: name');
    assert.equal(M.progressHeader(s), 'restoring 3 of 3');
    assert.equal(M.applyProgress(s, 'o1', f({ session_uuid: 'A', phase: 'restoring' })), false);
    M.applyProgress(s, 'o1', f({ session_uuid: 'C', phase: 'done', outcome: 'refused' }));
    assert.equal(M.progressWords(s.rows.C), 'failed: the server gave no reason');
    assert.match(M.progressHeader(s), /^all 3 settled/);
});

if (failures) { console.log(`${failures} FAILED`); process.exit(1); }
console.log('ALL PASS');
