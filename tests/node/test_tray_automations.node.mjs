
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const macDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'macOS');
const ta = require(path.join(macDir, 'tray-automations.js'));
const { TrayApiClient } = require(path.join(macDir, 'tray-api.js'));

const NOW = Date.UTC(2026, 9, 9, 12, 0, 0);
const S = NOW / 1000;
const TZ = 'UTC';
const row = (name, enabled, next, last) => ({ name, enabled, next_fire_at: next, last_run: last });
const run = (status, ended, reason = null) => ({ status, reason, ended_at: ended, started_at: ended - 5, slot_at: ended - 6 });

const body = {
  scheduler: { paused: false },
  automations: [
    row('weekly scrooge', true, S + 86400 * 3, run('succeeded', S - 100)),
    row('later today', true, S + 3600, run('failed', S - 10)),
    row('off one', false, S + 60, run('skipped', S - 5000, 'disabled')),
    row('soon', true, S + 600, null),
    row('fourth', true, S + 90000, run('succeeded', S - 99999)),
  ],
};
const labels = (items) => items.filter((i) => i.label).map((i) => i.label);
const calls = [];
const handlers = { onTogglePause: (v) => calls.push(['pause', v]), onOpen: () => calls.push(['open']), now: NOW, timeZone: TZ };

const snap = ta.summarize(body);
assert.equal(snap.reachable, true);
assert.deepEqual(snap.upcoming.map((u) => u.name), ['soon', 'later today', 'fourth']);
assert.deepEqual(snap.recent.map((r) => r.name), ['later today', 'weekly scrooge', 'off one']);
assert.equal(snap.recent[2].status, 'skipped: disabled');

const { automationRows, autonomyMenu } = require(path.join(macDir, 'tray-menu', 'model', 'autonomy.js'));
const t = (key, params) => ({ 'menubar.automations.next': 'next runs', 'menubar.automations.next_held': 'next runs, held while paused',
  'menubar.automations.none_scheduled': 'none scheduled', 'menubar.automations.last': 'last results',
  'menubar.automations.no_runs': 'no runs yet', 'menubar.automations.open': 'Open Automations...',
  'menubar.automations': 'automations', 'menubar.reason.unread': 'could not be read' }[key] || key);
const rowsText = (items) => items.map((i) => (i.sublabel ? `${i.label} - ${i.sublabel}` : i.label));
const text = rowsText(automationRows(snap, { t, now: NOW }));
assert.equal(text[0], 'next runs');
assert.ok(text.some((l) => /^soon - /.test(l)), text.join('\n'));
assert.ok(text.includes('later today - failed'));
assert.equal(text[text.length - 1], 'Open Automations...');
const pausedText = rowsText(automationRows(ta.summarize({ ...body, scheduler: { paused: true } }), { t, now: NOW }));
assert.equal(pausedText[0], 'next runs, held while paused');
const empty = rowsText(automationRows(ta.summarize({ automations: [] }), { t, now: NOW }));
assert.ok(empty.includes('none scheduled') && empty.includes('no runs yet'));
const down = automationRows(ta.summarize(null), { t, now: NOW });
assert.equal(down[0].sublabel, 'could not be read');
assert.ok(!rowsText(down).includes('none scheduled'));
assert.equal(automationRows(null, { t, now: NOW })[0].enabled, false);
const ok = (data) => ({ status: 'ok', data, error: null });
const menu = autonomyMenu({ now: NOW, routes: {}, side: { beast: ok({ enabled: false }), swarm: ok({ enabled: false }), automations: snap } }, { t });
assert.deepEqual(menu.submenu.find((i) => i.id === 'scheduler').action, { kind: 'autonomy.scheduler', paused: true });
void calls; void handlers; void labels;

const seen = [];
const fakeFetch = async (url, init) => {
  seen.push([init.method, url.replace('http://x', ''), init.headers.Authorization || null, init.body || null]);
  const data = url.endsWith('/auth/verify') ? { access_token: 'tok', expires_in: 14400, refresh_token: 'r' }
    : url.endsWith('/automations/scheduler') ? { paused: true } : body;
  return { ok: true, status: 200, json: async () => data };
};
const client = new TrayApiClient({ baseUrl: 'http://x', getOtp: () => '123456', fetchImpl: fakeFetch });
const fetched = await ta.fetchAutomationsSnapshot(client);
assert.equal(fetched.reachable, true);
assert.deepEqual((await ta.setSchedulerPaused(client, true)), { ok: true, error: null });
assert.deepEqual(seen.slice(-2), [
  ['GET', '/api/v1/automations', 'Bearer tok', null],
  ['PUT', '/api/v1/automations/scheduler', 'Bearer tok', '{"paused":true}'],
]);

const failing = new TrayApiClient({ baseUrl: 'http://x', getOtp: () => null, fetchImpl: fakeFetch });
assert.equal((await ta.fetchAutomationsSnapshot(failing)).reachable, false);
assert.equal((await ta.setSchedulerPaused(failing, true)).ok, false);

console.log('tray-automations: all assertions passed');
