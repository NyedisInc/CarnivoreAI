import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { load, macDir, env, snap } from './tray_menu_fixtures.mjs';

const require = createRequire(import.meta.url);
const { ListingStore } = load('listing-store.js');
const { EventsClient, eventsUrl, SUBPROTOCOL_MARKER } = load('events-client.js');
const portTrust = load('port-trust.js');
const offlineTmux = load('offline-tmux.js');
const { menuCapabilities, degradeItems } = load('capabilities.js');
const presenter = load('presenter.js');
const side = load('side-state.js');
const scripts = require(path.join(macDir, 'terminal-scripts.js'));

const info = (id, extra = {}) => ({ tmux_session: id, activity_status: 'idle', ...extra, session: { id, working_dir: '/w' } });
const snapshotBody = (stream, seq, rows) => ({ stream, seq, collections: { list: { ok: true, rows } } });
const flush = () => new Promise((r) => setImmediate(r));

test('listing store: a snapshot seeds, an in-order delta applies at both levels, a gap resyncs', async () => {
  let body = snapshotBody('s1', 5, [info('a'), info('b')]);
  let fetches = 0;
  const store = new ListingStore(async () => { fetches += 1; return body; });
  await store.hello();
  assert.equal(store.isLive(), true);
  assert.deepEqual(store.rows('list').map((r) => r.session.id), ['a', 'b']);
  const applied = store.frame({ stream: 's1', seq: 6, changes: { list: {
    upsert: [{ key: 'a', fields: { activity_status: 'question' }, nested: { session: { working_dir: '/x' } } }], remove: ['b'] } } });
  assert.equal(applied, 'applied');
  assert.equal(store.rows('list')[0].activity_status, 'question');
  assert.equal(store.rows('list')[0].session.working_dir, '/x');
  assert.equal(store.rows('list')[0].session.id, 'a', 'a nested patch keeps the other .session fields');
  assert.equal(store.rows('list').length, 1);
  assert.equal(store.frame({ stream: 's1', seq: 6, changes: { list: {} } }), 'ignored', 'a replay is ignored');
  body = snapshotBody('s1', 9, [info('c')]);
  assert.equal(store.frame({ stream: 's1', seq: 8, changes: { list: {} } }), 'resync', 'seq 7 was missed');
  await flush(); await flush();
  assert.equal(fetches, 2);
  assert.deepEqual(store.rows('list').map((r) => r.session.id), ['c']);
  body = snapshotBody('s2', 1, [info('d')]);
  assert.equal(store.frame({ stream: 's2', seq: 10, changes: { list: {} } }), 'resync', 'a new stream resyncs');
});

test('listing store: frames during a resync are buffered and replayed; a failed resync is not live', async () => {
  let release;
  const store = new ListingStore(() => new Promise((r) => { release = r; }));
  const pending = store.hello();
  assert.equal(store.frame({ stream: 's', seq: 3, changes: { list: { upsert: [{ key: 'a', fields: { unread: true } }] } } }), 'buffered');
  release(snapshotBody('s', 2, [info('a')]));
  await pending;
  assert.equal(store.isLive(), true);
  assert.equal(store.rows('list')[0].unread, true);
  const failing = new ListingStore(async () => { throw new Error('HTTP 503'); });
  await failing.hello();
  assert.equal(failing.isLive(), false);
  assert.equal(failing.lastError, 'HTTP 503');
  assert.equal(failing.rows('list'), null);
  failing.closed();
});

function fakeSockets() {
  const made = [];
  class FakeWS {
    constructor(url, protocols) { this.url = url; this.protocols = protocols; made.push(this); }
    close() { if (this.onclose) this.onclose({}); }
  }
  return { FakeWS, made };
}

function fakeTimers() {
  const timeouts = []; const intervals = [];
  return {
    timeouts, intervals,
    setTimeout: (fn, ms) => { timeouts.push({ fn, ms }); return timeouts.length; },
    clearTimeout: () => {},
    setInterval: (fn, ms) => { intervals.push({ fn, ms, live: true }); return intervals.length; },
    clearInterval: (id) => { if (intervals[id - 1]) intervals[id - 1].live = false; },
  };
}

test('events client: subprotocol auth, hello resyncs, a drop polls until the next hello', async () => {
  const { FakeWS, made } = fakeSockets();
  const timers = fakeTimers();
  let polls = 0; let hellos = 0;
  const store = { hello: () => { hellos += 1; return Promise.resolve(); }, closed: () => {}, frame: () => 'applied',
    poll: () => { polls += 1; return Promise.resolve(); } };
  const client = new EventsClient({ store, getBaseUrl: () => 'http://127.0.0.1:8000', getToken: async () => 'tok.en',
    forgetToken: () => {}, WebSocketImpl: FakeWS, timers, rng: () => 0 });
  client.start();
  await flush();
  assert.equal(made.length, 1);
  assert.equal(made[0].url, 'ws://127.0.0.1:8000/ws/events');
  assert.deepEqual(made[0].protocols, [SUBPROTOCOL_MARKER, 'tok.en'], 'the token rides the subprotocol, never the URL');
  made[0].onmessage({ data: JSON.stringify({ type: 'events.hello', resource_topics: [] }) });
  assert.equal(hellos, 1);
  assert.equal(polls, 0, 'no polling while the socket is up');
  made[0].onclose({});
  assert.equal(polls, 1, 'a drop polls at once');
  assert.equal(timers.intervals.filter((i) => i.live).length, 1);
  assert.equal(timers.timeouts.at(-1).ms, 1000, 'first reconnect after the minimum backoff');
  timers.timeouts.at(-1).fn();
  await flush();
  made[1].onmessage({ data: JSON.stringify({ type: 'events.hello' }) });
  assert.equal(timers.intervals.filter((i) => i.live).length, 0, 'the next hello stops the poll');
  client.stop();
  assert.equal(eventsUrl('https://h:1/'), 'wss://h:1/ws/events');
});

test('events client: no token means no socket, and two refusals before hello forget the token', async () => {
  const { FakeWS, made } = fakeSockets();
  const timers = fakeTimers();
  let forgotten = 0;
  const store = { hello: () => Promise.resolve(), closed: () => {}, frame: () => {}, poll: () => Promise.resolve() };
  const none = new EventsClient({ store, getBaseUrl: () => 'http://h:1', getToken: async () => null, forgetToken: () => {}, WebSocketImpl: FakeWS, timers });
  none.start(); await flush();
  assert.equal(made.length, 0);
  none.stop();
  const client = new EventsClient({ store, getBaseUrl: () => 'http://h:1', getToken: async () => 't', forgetToken: () => { forgotten += 1; },
    WebSocketImpl: FakeWS, timers, rng: () => 0 });
  client.start(); await flush();
  made.at(-1).onclose({});
  timers.timeouts.at(-1).fn(); await flush();
  made.at(-1).onclose({});
  assert.equal(forgotten, 1);
  client.stop();
});

test('port trust: own process with the Carnivore health shape is trusted; a stranger or a non-Carnivore is refused', () => {
  const holders = portTrust.parseLsof('p4312\ncpython3.12\nu501\np99\ncnode\nu0\n');
  assert.deepEqual(holders, [{ pid: 4312, command: 'python3.12', uid: 501 }, { pid: 99, command: 'node', uid: 0 }]);
  const health = { status: 'running', uptime: 3, version: '1.16.1', local_server_count: 0 };
  assert.equal(portTrust.judgePort({ holders: [holders[0]], myUid: 501, health }).trusted, true);
  const stranger = portTrust.judgePort({ holders, myUid: 501, health });
  assert.deepEqual([stranger.trusted, stranger.reason, stranger.holder.pid], [false, 'not_yours', 99]);
  assert.equal(portTrust.judgePort({ holders: [holders[0]], myUid: 501, health: { ok: true } }).reason, 'not_carnivore');
  assert.equal(portTrust.judgePort({ holders: [], myUid: 501, health }).trusted, null, 'no listener seen is cannot-determine');
  assert.equal(portTrust.describeHolder(holders[1]), 'PID 99 (node, uid 0)');
});

test('kill port holder: refuses another user, Electron and tmux; re-checks identity right before it signals', async () => {
  const me = { myUid: 501, myPid: 10 };
  assert.match(portTrust.killRefusal({ pid: 5, uid: 0, name: 'python3' }, me), /another user/);
  assert.match(portTrust.killRefusal({ pid: 10, uid: 501, name: 'x' }, me), /never stopped/);
  assert.match(portTrust.killRefusal({ pid: 6, uid: 501, name: 'tmux' }, me), /never stopped/);
  assert.equal(portTrust.killRefusal({ pid: 7, uid: 501, name: 'python3' }, me), null);
  const answers = { lsof: 'p7\ncpython3\nu501\n', ps: 'Fri Oct 17 10:00:00 2026 /usr/bin/python3\n' };
  const signals = [];
  const deps = { ...me, kill: (pid, sig) => signals.push([pid, sig]), sleep: async () => {},
    execFile: (file, args, opts, cb) => cb(null, file.endsWith('lsof') ? answers.lsof : answers.ps) };
  const holder = await portTrust.identifyHolder(8000, deps);
  assert.deepEqual(holder, { pid: 7, uid: 501, start: 'Fri Oct 17 10:00:00 2026', exe: '/usr/bin/python3', name: 'python3' });
  answers.ps = 'Fri Oct 17 11:00:00 2026 /usr/bin/python3\n';
  const changed = await portTrust.killHolder(8000, holder, deps);
  assert.equal(changed.stopped, false, 'a recycled pid is not the process he confirmed');
  assert.deepEqual(signals, []);
  answers.ps = 'Fri Oct 17 10:00:00 2026 /usr/bin/python3\n';
  const done = await portTrust.killHolder(8000, holder, deps);
  assert.equal(done.stopped, true);
  assert.deepEqual(signals, [[7, 'SIGTERM'], [7, 'SIGKILL']], 'still there after the grace: SIGKILL');
});

test('offline tmux count: list-sessions on our socket, never a server-starting word, no server is "gone"', async () => {
  const argv = offlineTmux.listSessionsArgv('/tmp/tmux-501/cloude');
  assert.deepEqual(argv.slice(0, 5), ['-f', '/dev/null', '-S', '/tmp/tmux-501/cloude', 'list-sessions']);
  for (const word of scripts.FORBIDDEN_TMUX_WORDS) assert.ok(!argv.includes(word), word);
  const fsOk = { readFileSync: () => '{}', existsSync: () => true };
  const run = (err, out, stderr) => ({ fs: fsOk, uid: 501, execFile: (bin, args, opts, cb) => cb(err, out, stderr) });
  assert.deepEqual(await offlineTmux.readAliveCount({ serverDir: '/s', tmuxBin: '/opt/homebrew/bin/tmux', deps: run(null, 'a\nb\nc\n', '') }),
    { alive: 3, tmuxRunning: true, error: null });
  assert.deepEqual(await offlineTmux.readAliveCount({ serverDir: '/s', tmuxBin: '/t', deps: run(new Error('x'), '', 'no server running on /tmp/x') }),
    { alive: 0, tmuxRunning: false, error: null });
  assert.equal((await offlineTmux.readAliveCount({ serverDir: '/s', tmuxBin: null, deps: run(null, '', '') })).alive, null);
});

test('capability shim: header and badge need macOS 14, sublabel 14.4; a disabled reason stays visible', () => {
  assert.deepEqual(menuCapabilities('darwin', '26.0'), { header: true, sublabel: true, badge: true });
  assert.deepEqual(menuCapabilities('darwin', '14.2'), { header: true, sublabel: false, badge: true });
  assert.deepEqual(menuCapabilities('darwin', '13.6'), { header: false, sublabel: false, badge: false });
  assert.deepEqual(menuCapabilities('linux', '6.1'), { header: false, sublabel: false, badge: false });
  const out = degradeItems([{ type: 'header', id: 'h', label: 'Carnivore', sublabel: 'running' },
    { type: 'normal', id: 'x', label: 'Keep Mac Awake', enabled: false, sublabel: 'needs a newer server' },
    { type: 'normal', id: 'y', label: 'Copy URL', enabled: true, sublabel: 'http://h' },
    { type: 'submenu', id: 'n', label: '2 Need You', badge: { type: 'alerts', count: 2 }, submenu: [] }], menuCapabilities('darwin', '13.6'));
  assert.deepEqual(out.map((i) => [i.type, i.label, i.enabled]), [['normal', 'Carnivore', false], ['normal', 'running', false],
    ['normal', 'Keep Mac Awake (needs a newer server)', false], ['normal', 'Copy URL', true], ['submenu', '2 Need You', undefined]]);
  assert.equal(out[3].toolTip, 'http://h');
  assert.equal(out[4].badge, undefined);
});

test('darwin presenter: builds on click from a fresh model and pops it; double clicks ignored; Option adds Debug', () => {
  const events = {}; const pops = []; let ignore = null; let built = 0;
  const tray = { on: (e, fn) => { events[e] = fn; }, popUpContextMenu: (m) => pops.push(m), setIgnoreDoubleClickEvents: (v) => { ignore = v; },
    setContextMenu: () => { throw new Error('darwin never sets a context menu'); } };
  const Menu = { buildFromTemplate: (tpl) => ({ tpl }) };
  const { buildMenuModel } = load('model/index.js');
  const dispatched = [];
  const p = presenter.createDarwinPresenter({ tray, Menu, caps: menuCapabilities('darwin', '26.0'), dispatch: (a) => dispatched.push(a),
    buildItems: ({ optionKey }) => { built += 1; return buildMenuModel(snap({ optionKey }), env); } });
  assert.equal(ignore, true);
  assert.equal(built, 0, 'nothing is built until he clicks');
  events.click({ altKey: false });
  assert.equal(pops.length, 1);
  assert.ok(!pops[0].tpl.some((i) => i.label === 'Debug'));
  events.click({ altKey: true });
  assert.ok(pops[1].tpl.some((i) => i.label === 'Debug'));
  const quit = pops[0].tpl.find((i) => i.label === 'Quit Carnivore');
  assert.equal(quit.accelerator, 'CommandOrControl+Q');
  quit.click();
  assert.deepEqual(dispatched, [{ kind: 'app.quit' }]);
  assert.equal(pops[0].tpl[0].type, 'header');
  assert.ok(p.menuForDock().tpl.length > 5, 'the Dock pops an explicitly built menu');
});

test('dispatcher: every model action kind has exactly one handler', () => {
  const { allHandlers } = load('actions/index.js');
  const table = allHandlers({ serverManager: {}, dialog: {} });
  const { buildMenuModel } = load('model/index.js');
  const { row } = { row: (id, x = {}) => ({ tmux_session: `c_${id}`, activity_status: 'question', ...x, session: { id } }) };
  const kinds = new Set();
  const visit = (items) => items.forEach((i) => { if (i.action) kinds.add(i.action.kind); if (i.submenu) visit(i.submenu); });
  visit(buildMenuModel(snap({ optionKey: true, listing: { rows: [row('a'), row('b', { startup_gate: 'awaiting_startup_prompt' })] },
    update: { state: 'ready', version: '2' }, setup: 'incomplete' }), env));
  visit(buildMenuModel(snap({ optionKey: true, offlineTuiAvailable: true, server: { state: 'stopped', portHolder: 'PID 1' } }), env));
  for (const kind of kinds) assert.equal(typeof table[kind], 'function', kind);
});

test('side state: 404 is "missing", other failures "unknown"; debug always carries its expiry', () => {
  assert.equal(side.classify({ reachable: false, status: 404 }).status, 'missing');
  assert.equal(side.classify({ reachable: false, status: 0, error: 'ECONNREFUSED' }).status, 'unknown');
  assert.equal(side.classify({ reachable: true, status: 200, data: { always: true } }).data.always, true);
  assert.deepEqual(side.logLevelBody('debug'), { level: 'debug', expires_in_s: 1800 });
  assert.deepEqual(side.logLevelBody('info'), { level: 'info' });
});

test('Watch in Terminal attaches read-only and never falls back to a claude; the attach command is exact', () => {
  const spec = { tmuxBin: '/opt/homebrew/bin/tmux', socketPath: '/tmp/tmux-501/cloude', tmuxName: 'carnivore_a', folder: '/w',
    homeFolder: '/Users/j', shellBin: '/bin/zsh', claudeBin: 'claude', label: 'a' };
  const watch = scripts.buildSessionScript({ ...spec, readOnly: true });
  assert.match(watch, /attach-session -r -t "\$TARGET"/);
  assert.ok(!/CLAUDE_BIN"\s*$/m.test(watch) && !/exec "\$CLAUDE_BIN"/.test(watch), 'watch never starts claude');
  const type = scripts.buildSessionScript(spec);
  assert.match(type, /attach-session -t "\$TARGET"/);
  assert.match(type, /exec "\$CLAUDE_BIN"/);
  assert.equal(scripts.attachCommand({ tmuxBin: null, socketPath: '/tmp/tmux-501/cloude', tmuxName: 'carnivore_a' }),
    "tmux -f /dev/null -S '/tmp/tmux-501/cloude' attach-session -t '=carnivore_a'");
  assert.throws(() => scripts.attachCommand({ tmuxBin: null, socketPath: '/tmp/x', tmuxName: '' }), 'an empty name is refused');
});
