import test from 'node:test';
import assert from 'node:assert/strict';
import { load, env, snap, byId } from './tray_menu_fixtures.mjs';

const side = load('side-state.js');
const { ListingStore } = load('listing-store.js');
const { EventsClient } = load('events-client.js');
const { createTrayData } = load('data.js');
const { buildMenuModel } = load('model/index.js');
const flush = async () => { for (let i = 0; i < 6; i += 1) await new Promise((r) => setImmediate(r)); };

function fakeTimers() {
  const t = { timeouts: [], intervals: [] };
  t.setTimeout = (fn, ms) => { t.timeouts.push({ fn, ms, live: true }); return t.timeouts.length; };
  t.clearTimeout = (id) => { if (t.timeouts[id - 1]) t.timeouts[id - 1].live = false; };
  t.setInterval = (fn, ms) => { t.intervals.push({ fn, ms, live: true }); return t.intervals.length; };
  t.clearInterval = (id) => { if (t.intervals[id - 1]) t.intervals[id - 1].live = false; };
  return t;
}

function fakeSockets() {
  const made = [];
  class FakeWS { constructor(url, protocols) { this.url = url; this.protocols = protocols; made.push(this); } close() { if (this.onclose) this.onclose({}); } }
  return { FakeWS, made };
}

function rig(lsofUid = 501) {
  const reads = [];
  const timers = fakeTimers();
  const { FakeWS, made } = fakeSockets();
  class FakeApi {
    setBaseUrl() {}
    forgetToken() {}
    async ensureToken() { return { token: 'tok' }; }
    async getAuthed(p) {
      reads.push(p);
      if (p.startsWith('/api/v1/sessions/listing')) return { reachable: true, status: 200, data: { stream: 's', seq: 1, collections: { list: { ok: true, rows: [] } } } };
      return { reachable: true, status: 200, data: {} };
    }
  }
  const sm = { getState: () => 'running', getPort: () => 8000, getLocalApiUrl: () => 'http://127.0.0.1:8000', getCurrentOtp: () => null, baseDir: '/s' };
  const data = createTrayData({ serverManager: sm, member: { isJoined: () => false, tokens: null }, TrayApiClient: FakeApi, onChange: () => {},
    portDeps: () => ({ myUid: 501, myPid: 1, execFile: (f, a, o, cb) => cb(null, `p42\ncpython3\nu${lsofUid}\n`) }),
    offlineDeps: () => ({}), resolveTmux: async () => null, WebSocketImpl: FakeWS, timers });
  return { data, reads, timers, made };
}
const health = { status: 'running', uptime: 1, version: '1.16.1' };
const sideReads = (reads) => reads.filter((p) => !p.startsWith('/api/v1/sessions/listing'));

test('1. side resources re-read only when their topic fires; the timer polls only topics hello lacks', async () => {
  const r = rig();
  await r.data.onHealth(health);
  await flush();
  r.reads.length = 0;
  r.made[0].onmessage({ data: JSON.stringify({ type: 'events.hello', resource_topics: ['beast_mode', 'automations', 'automation_runs', 'swarm_roster', 'auto_sleep', 'app_update', 'desktop_preferences'] }) });
  await flush();
  assert.equal(sideReads(r.reads).length, 9, 'hello re-reads every side resource once');
  r.reads.length = 0;
  r.made[0].onmessage({ data: JSON.stringify({ type: 'resources.changed', topics: ['beast_mode'], seq: 3 }) });
  await flush();
  assert.deepEqual(sideReads(r.reads), ['/api/v1/beast-mode'], 'a topic re-reads its one resource');
  r.reads.length = 0;
  r.timers.intervals.find((i) => i.ms === 30000).fn();
  await flush();
  assert.deepEqual(sideReads(r.reads), ['/api/v1/swarm/switch'], 'only the resource whose topic hello lacked is polled');
  r.reads.length = 0;
  r.made[0].onclose({});
  r.timers.intervals.find((i) => i.ms === 30000).fn();
  await flush();
  assert.equal(sideReads(r.reads).length, 7, 'socket down: every topic resource polls; topic-less ones never on the timer');
  assert.deepEqual(side.resourcesForTopics(['automation_runs', 'nope']), ['automations']);
  assert.deepEqual(side.resourcesForTopics(['desktop_preferences']), ['desktopPrefs'], 'R1-03: the menu bar icon follows the preferences topic');
  assert.equal(side.onOpenReads(new Set(['desktop_preferences'])).includes('desktopPrefs'), false, 'a pushed preferences read is not repeated on menu open');
  assert.deepEqual(side.onOpenReads(new Set(['beast_mode', 'app_update'])).sort(), ['account', 'automations', 'desktopPrefs', 'keepAwake', 'logLevel', 'swarm', 'sysop']);
  r.data.stop();
});

test('2. a failed resync after hello retries with bounded backoff and counts as socket-down for polling', async () => {
  const timers = fakeTimers();
  let fail = true; let fetches = 0;
  const store = new ListingStore(async () => { fetches += 1; if (fail) throw new Error('HTTP 503'); return { stream: 's', seq: 1, collections: { list: { ok: true, rows: [] } } }; }, timers);
  const { FakeWS, made } = fakeSockets();
  let polls = 0;
  const origPoll = store.poll.bind(store);
  store.poll = () => { polls += 1; return origPoll().catch(() => {}); };
  const client = new EventsClient({ store, getBaseUrl: () => 'http://h:1', getToken: async () => 't', forgetToken: () => {}, WebSocketImpl: FakeWS, timers, rng: () => 0 });
  client.start();
  await flush();
  made[0].onmessage({ data: JSON.stringify({ type: 'events.hello' }) });
  await flush();
  assert.equal(store.isLive(), false);
  assert.ok(polls >= 1, 'a failed resync starts the snapshot poll');
  const retry = timers.timeouts.filter((x) => x.live).at(-1);
  assert.equal(retry.ms, 1000, 'first retry after one second');
  retry.fn(); await flush();
  assert.equal(timers.timeouts.filter((x) => x.live).at(-1).ms, 2000, 'the backoff doubles');
  fail = false;
  timers.timeouts.filter((x) => x.live).at(-1).fn(); await flush();
  assert.equal(store.isLive(), true, 'the retry succeeded and the store is live');
  assert.equal(timers.intervals.filter((i) => i.live).length, 0, 'live again: the poll stopped');
  assert.ok(fetches >= 3);
  client.stop();
});

test('3. Stand Down: a failed step or a non-2xx answer is a failure, never "already off"', () => {
  const { standDownReport } = load('actions/autonomy.js');
  const partial = standDownReport({ reachable: true, status: 200, data: { beast_off: true, swarm_off: false, scheduler_paused: true, failed: ['swarm'] } });
  assert.equal(partial.ok, false);
  assert.match(partial.detail, /These steps failed: swarm\./);
  assert.match(partial.detail, /Beast Mode is off\./);
  const allFailed = standDownReport({ reachable: false, status: 500, data: null, body: { beast_off: false, swarm_off: false, scheduler_paused: false, failed: ['beast', 'swarm', 'scheduler'] } });
  assert.equal(allFailed.ok, false);
  assert.match(allFailed.detail, /beast, swarm, scheduler/);
  assert.doesNotMatch(allFailed.detail, /already off/);
  const noBody = standDownReport({ reachable: false, status: 502, data: null, error: 'HTTP 502' });
  assert.equal(noBody.ok, false);
  assert.match(noBody.detail, /HTTP 502/);
  const idle = standDownReport({ reachable: true, status: 200, data: { beast_off: false, swarm_off: false, scheduler_paused: false, failed: [] } });
  assert.equal(idle.ok, true);
  assert.match(idle.detail, /Everything was already off\./);
});

test('4. Start in Debug Mode sets CARNIVORE_DEBUG_BOOT=1 for that one spawn, then restores it; LOG_LEVEL untouched', async () => {
  const { handlers, DEBUG_BOOT_ENV } = load('actions/troubleshoot.js');
  assert.equal(DEBUG_BOOT_ENV, 'CARNIVORE_DEBUG_BOOT');
  for (const prior of [undefined, '0']) {
    const fakeEnv = { LOG_LEVEL: 'warn' };
    if (prior !== undefined) fakeEnv.CARNIVORE_DEBUG_BOOT = prior;
    const seen = [];
    const sm = { resetSupervisor() {}, async start() { seen.push({ ...fakeEnv }); } };
    await handlers({ serverManager: sm, env: fakeEnv, refresh() {}, reportStartFailure: async () => {} })['server.start_debug']();
    assert.equal(seen[0].CARNIVORE_DEBUG_BOOT, '1');
    assert.equal(seen[0].LOG_LEVEL, 'warn');
    if (prior === undefined) assert.ok(!('CARNIVORE_DEBUG_BOOT' in fakeEnv));
    else assert.equal(fakeEnv.CARNIVORE_DEBUG_BOOT, '0');
  }
  const fakeEnv = {};
  const failures = [];
  const sm = { resetSupervisor() {}, async start() { throw new Error('port held'); } };
  await handlers({ serverManager: sm, env: fakeEnv, refresh() {}, reportStartFailure: async (e) => failures.push(e.message) })['server.start_debug']();
  assert.deepEqual(failures, ['port held']);
  assert.ok(!('CARNIVORE_DEBUG_BOOT' in fakeEnv), 'restored after a failed start too');
});

test('5. signed out: a Sign In to Carnivore... row opens #account; signed in: the account is the Settings sublabel', () => {
  const out = buildMenuModel(snap({ side: { account: null } }), env);
  assert.deepEqual(byId(out, 'account.sign_in').action, { kind: 'app.account' });
  assert.equal(byId(out, 'account.sign_in').label, 'Sign In to Carnivore...');
  assert.equal(byId(out, 'settings').sublabel, undefined);
  const inside = buildMenuModel(snap(), env);
  assert.equal(byId(inside, 'account.sign_in'), undefined);
  assert.equal(byId(inside, 'settings').sublabel, 'signed in as sam');
  const opened = [];
  const { handlers } = load('actions/app.js');
  handlers({ serverManager: { getPublishedUrl: () => 'http://203.0.113.12:8000', getState: () => 'running' }, shell: { openExternal: (u) => opened.push(u) } })['app.account']();
  assert.deepEqual(opened, ['http://203.0.113.12:8000/#account']);
});

test('6. an untrusted port holder: why row, Kill Port Holder and Start Server agree', async () => {
  const r = rig(0);
  await r.data.onHealth(health);
  const parts = r.data.parts();
  assert.equal(parts.portTrust.trusted, false);
  assert.equal(parts.portHolder, 'PID 42 (python3, uid 0)', 'read while the state is running, not only when stopped');
  assert.equal(r.made.length, 0, 'nothing is opened to an untrusted port');
  const items = buildMenuModel(snap({ server: { portTrust: parts.portTrust, portHolder: parts.portHolder } }), env);
  assert.equal(items[1].label, 'why: port held by PID 42 (python3, uid 0)');
  assert.equal(byId(items, 'server.kill_port').enabled, true);
  assert.equal(byId(items, 'server.start').enabled, false);
  assert.equal(byId(items, 'server.start').sublabel, 'port in use');
  const viaTrust = buildMenuModel(snap({ server: { portTrust: parts.portTrust, portHolder: null } }), env);
  assert.equal(byId(viaTrust, 'server.kill_port').enabled, true, 'the model also reads the holder off the failed trust');
});

test('7. a stop() and start() during the token mint never opens a second socket', async () => {
  const { FakeWS, made } = fakeSockets();
  const pending = [];
  const store = { hello: () => Promise.resolve(), closed: () => {}, frame: () => {}, poll: () => Promise.resolve(), isLive: () => false, onChange: () => () => {} };
  const client = new EventsClient({ store, getBaseUrl: () => 'http://h:1', getToken: () => new Promise((r) => pending.push(r)),
    forgetToken: () => {}, WebSocketImpl: FakeWS, timers: fakeTimers() });
  client.start();
  client.stop();
  client.start();
  pending.forEach((resolve) => resolve('tok'));
  await flush();
  assert.equal(made.length, 1);
  client.stop();
});
