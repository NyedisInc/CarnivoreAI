import test from 'node:test';
import assert from 'node:assert/strict';
import { load, env, snap, row, walk, byId, catalogKeys } from './tray_menu_fixtures.mjs';

const { buildMenuModel } = load('model/index.js');
const labels = (items) => items.filter((i) => i.type !== 'separator').map((i) => i.label);
const build = (over) => buildMenuModel(snap(over), env);

test('server running: the top-level rows in the drawn order', () => {
  assert.deepEqual(labels(build()), ['Carnivore', 'Open Carnivore', 'Sessions (0)', 'New Session...', 'Phone Access', 'Keep Mac Awake',
    'Autonomy', 'Server & Troubleshoot', 'Open in Browser', 'Settings...', 'Check for Updates...', 'About Carnivore', 'Quit Carnivore', 'Quit and Stop Engine']);
  const header = build()[0];
  assert.equal(header.type, 'header');
  assert.equal(header.sublabel, 'running · v1.16.1 · phone reachable');
});

test('header sublabel appends beast on, swarm on and local servers only when true', () => {
  const ok = (data) => ({ status: 'ok', data, error: null });
  const items = build({ side: { beast: ok({ enabled: true, available: true }), swarm: ok({ enabled: true }) }, server: { localServerCount: 2 } });
  assert.equal(items[0].sublabel, 'running · v1.16.1 · phone reachable · beast on · swarm on · 2 local servers');
  assert.match(build({ phone: { effectiveHost: '127.0.0.1' } })[0].sublabel, /this mac only/);
});

test('Restart to Update and Finish Setup appear only when staged or definitely incomplete', () => {
  const ids = (o) => build(o).map((i) => i.id);
  assert.ok(!ids().includes('update.install') && !ids().includes('setup.finish'));
  assert.ok(ids({ update: { state: 'ready', version: '1.17.0' } }).includes('update.install'));
  assert.ok(ids({ setup: 'incomplete' }).includes('setup.finish'));
  assert.ok(!ids({ setup: 'undetermined' }).includes('setup.finish'), 'a server that could not be asked must not send him to setup');
});

test('Need You: counted by StatusLed.ledStateFor, question routes to approvals, gate to the session', () => {
  const rows = [row('1', { activity_status: 'question' }), row('2', { startup_gate: 'awaiting_startup_prompt' }),
    row('3', { activity_status: 'notice' }), row('4', { activity_status: 'working' }), row('5', { activity_status: 'question', host_key: 'p', host_state: 'disconnected' })];
  const items = build({ listing: { rows } });
  const need = items.find((i) => i.id === 'needyou');
  assert.equal(need.label, '2 Need You', 'notice is light blue, not yellow; an unreachable peer is red');
  assert.deepEqual(need.badge, { type: 'alerts', count: 2 });
  assert.deepEqual(need.submenu.map((i) => i.action.need), ['question', 'gate']);
  assert.equal(need.submenu[0].action.kind, 'session.attention');
  assert.equal(need.submenu[0].action.sessionId, 'ses_1', 'ids come from .session (gotcha 1)');
  assert.equal(build().find((i) => i.id === 'needyou'), undefined, 'no row at zero');
});

test('Sessions: need-you first, then the 8 most recent local, then one row per other computer, All Sessions last', () => {
  const rows = [];
  for (let n = 1; n <= 10; n += 1) rows.push(row(String(n), { at: `2026-10-17T${String(n).padStart(2, '0')}:00:00Z` }));
  rows.push(row('11', { activity_status: 'question', at: '2026-10-01T00:00:00Z' }));
  rows.push(row('12', { host_key: 'peer-a', host_label: 'studio' }), row('13', { host_key: 'peer-a', host_label: 'studio' }));
  const sessions = build({ listing: { rows } }).find((i) => i.id === 'sessions');
  assert.equal(sessions.label, 'Sessions (13)');
  const names = labels(sessions.submenu);
  assert.deepEqual(names.slice(0, 9), ['label 11', 'label 10', 'label 9', 'label 8', 'label 7', 'label 6', 'label 5', 'label 4', 'label 3']);
  assert.ok(!names.includes('label 2') && !names.includes('label 1'), 'only eight recent local rows');
  const peer = sessions.submenu.find((i) => i.id === 'peer.peer-a');
  assert.equal(peer.label, 'studio');
  assert.equal(peer.sublabel, '2 sessions on that computer');
  assert.deepEqual(peer.action, { kind: 'app.open', hash: '#pack/computers' });
  assert.deepEqual(names.slice(-3), ['SysOp in Terminal', 'Open Terminal', 'All Sessions...']);
});

test('Sessions: per-row actions, terminal rows disabled with a reason for peer, asleep and dead', () => {
  const rows = [row('1'), row('2', { activity_status: 'asleep' }), row('3', { activity_status: 'dead' }),
    row('4', { activity_status: 'question', host_key: 'peer-a' })];
  const sessions = build({ listing: { rows } }).find((i) => i.id === 'sessions');
  const local = sessions.submenu.find((i) => i.id === 'session.row:1');
  assert.deepEqual(labels(local.submenu), ['Open in App', 'Watch in Terminal', 'Type in Terminal', 'Copy Attach Command', 'Restart...']);
  assert.deepEqual(local.submenu[1].action, { kind: 'session.terminal', mode: 'watch', tmuxName: 'carnivore_1', sessionId: 'ses_1', folder: '/w/1', label: 'label 1' });
  for (const [id, reason] of [['session.row:2', 'asleep: wake it in the app'], ['session.row:3', 'its pane is dead'], ['session.row:4', 'on another computer']]) {
    const sub = sessions.submenu.find((i) => i.id === id).submenu;
    for (const n of [1, 2, 3]) {
      assert.equal(sub[n].enabled, false, `${id} ${sub[n].label}`);
      assert.equal(sub[n].sublabel, reason);
    }
    assert.equal(sub[0].enabled, true, 'Open in App always works');
  }
});

test('Sessions: an unreadable listing says so instead of an empty list', () => {
  const sessions = build({ listing: { reachable: false, rows: null, error: 'HTTP 500' } }).find((i) => i.id === 'sessions');
  assert.equal(sessions.label, 'Sessions');
  assert.equal(sessions.submenu[0].label, 'sessions could not be read');
  assert.equal(sessions.submenu[0].sublabel, 'HTTP 500');
});

test('server down: the calm path first, with the tmux count from the offline path', () => {
  const items = build({ server: { state: 'stopped' }, offline: { alive: 12, tmuxRunning: true } });
  assert.deepEqual(labels(items), ['Carnivore', 'why: the server was stopped', 'Start Server', 'Terminal (Offline)...',
    'Open Server Log in Console', 'Copy Diagnostics', 'Export Diagnostics...', 'Server & Troubleshoot', 'Settings...', 'Check for Updates...', 'About Carnivore', 'Quit Carnivore', 'Quit and Stop Engine']);
  assert.equal(items[0].sublabel, 'server stopped · 12 agents alive in tmux');
  assert.equal(byId(items, 'settings').enabled, false);
  assert.equal(byId(items, 'settings').sublabel, 'needs the server');
  assert.match(build({ server: { state: 'stopped' }, offline: { alive: 0, tmuxRunning: false } })[0].sublabel, /tmux not running: sessions are gone/);
  const gaveUp = build({ server: { state: 'stopped', supervisor: { gaveUp: true, pending: false, attempts: 5, maxAttempts: 5, message: 'x' } } });
  assert.equal(byId(gaveUp, 'server.start').label, 'Restart Server');
  assert.equal(byId(gaveUp, 'server.why').label, 'why: automatic restart gave up after 5 attempts');
});

test('a port that failed the ownership check is the down layout, naming the holder', () => {
  const items = build({ server: { portTrust: { trusted: false, reason: 'not_yours', holderText: 'PID 9 (python3, uid 0)' } } });
  assert.equal(items[1].label, 'why: port held by PID 9 (python3, uid 0)');
  assert.ok(!byId(items, 'sessions'), 'nothing that would talk to the server is offered');
});

test('Kill Port Holder needs a holder; Option-click adds Debug with the log level radios', () => {
  const down = build({ server: { state: 'stopped', portHolder: 'PID 77 (node, uid 501)' } });
  assert.equal(byId(down, 'server.kill_port').enabled, true);
  assert.equal(byId(down, 'server.kill_port').sublabel, 'PID 77 (node, uid 501)');
  assert.equal(byId(build({ server: { state: 'stopped' } }), 'server.kill_port').enabled, false);
  const debug = byId(build({ optionKey: true }), 'debug');
  assert.deepEqual(debug.submenu.filter((i) => i.type === 'radio').map((i) => [i.label, i.checked]),
    [['Error', false], ['Warn', false], ['Info', true], ['Debug', false]]);
  assert.equal(byId(debug.submenu, 'debug.level.debug').sublabel, 'turns itself off after 30 minutes');
  assert.equal(byId(build(), 'debug'), undefined);
});

test('a route the server lacks disables its row with "needs a newer server"', () => {
  const missing = { status: 'missing', data: null, error: null };
  const items = build({ side: { keepAwake: missing, logLevel: missing }, routes: { standDown: 'missing' }, optionKey: true });
  assert.equal(byId(items, 'keep_awake').enabled, false);
  assert.equal(byId(items, 'keep_awake').sublabel, 'needs a newer server');
  assert.equal(byId(items, 'stand_down').enabled, false);
  assert.equal(byId(items, 'stand_down').sublabel, 'needs a newer server');
  assert.equal(byId(items, 'debug.level').sublabel, 'needs a newer server');
  const expiry = build({ routes: { logLevelExpiry: 'missing' }, optionKey: true });
  assert.equal(byId(expiry, 'debug.level.debug').enabled, false, 'debug is never set without its expiry');
  const kept = byId(build({ side: { keepAwake: { status: 'ok', data: { always: true }, error: null } } }), 'keep_awake');
  assert.deepEqual([kept.type, kept.checked, kept.action], ['checkbox', true, { kind: 'autonomy.keep_awake', always: false }]);
});

test('Beast Mode: off in one click, on only through the grid; Phone Access uses the measured URL only', () => {
  const ok = (data) => ({ status: 'ok', data, error: null });
  assert.deepEqual(byId(build({ side: { beast: ok({ enabled: true, available: true }) } }), 'beast').action, { kind: 'autonomy.beast_off' });
  assert.deepEqual(byId(build(), 'beast').action, { kind: 'autonomy.beast_open' });
  assert.equal(byId(build({ side: { beast: ok({ enabled: false, available: false }) } }), 'beast').enabled, false);
  const noUrl = build({ phone: { measuredUrl: null } });
  assert.equal(byId(noUrl, 'phone.copy_url').enabled, false);
  assert.equal(byId(noUrl, 'phone.copy_url').sublabel, 'unavailable: bind not measured');
  const joined = build({ joined: true });
  assert.equal(byId(joined, 'phone.copy_otp'), undefined, 'a pack member has no authenticator of its own');
  assert.equal(byId(joined, 'phone.totp_qr'), undefined);
  assert.equal(byId(build(), 'bind.0.0.0.0'), undefined);
  assert.equal(byId(build(), 'bind.all').checked, true);
});

test('only Cmd-, and Cmd-Q carry accelerators; Quit keeps its sublabel; every key exists; no dashes or emoji', () => {
  const keys = [];
  const rows = [row('1', { activity_status: 'question' }), row('2', { host_key: 'p' })];
  for (const items of [build({ listing: { rows }, optionKey: true, update: { state: 'ready', version: '2' }, setup: 'incomplete' }),
    build({ server: { state: 'stopped' }, optionKey: true })]) {
    walk(items, (i) => {
      if (i.accelerator) keys.push(i.accelerator);
      for (const text of [i.label, i.sublabel].filter(Boolean)) {
        assert.ok(!text.startsWith('menubar.'), `missing catalog key rendered: ${text}`);
        assert.ok(!/[\u2013\u2014]|\p{Extended_Pictographic}/u.test(text), text);
      }
    });
  }
  assert.deepEqual([...new Set(keys)].sort(), ['CommandOrControl+,', 'CommandOrControl+Q']);
  assert.equal(byId(build(), 'quit').sublabel, 'agents keep running; desktop banners stop');
  assert.equal(byId(build(), 'quit_stop').sublabel, 'stops the engine and phone alerts; agents keep running');
  assert.deepEqual(byId(build(), 'quit_stop').action, { kind: 'app.quit_stop' });
  assert.ok(catalogKeys.has('menubar.quit'));
  assert.ok(catalogKeys.has('menubar.quit_stop'));
});

test('labels are truncated', () => {
  const long = 'x'.repeat(200);
  const sessions = build({ listing: { rows: [row('1', { label: long })] } }).find((i) => i.id === 'sessions');
  assert.ok(sessions.submenu[0].label.length <= load('strings.js').MAX_LABEL && sessions.submenu[0].label.endsWith('...'));
});

test('server down with the slow port retry armed: a Stop Retrying row cancels it, and it is absent otherwise (#2527)', () => {
  const sup = (slowRetry) => ({ gaveUp: true, pending: false, slowRetry, attempts: 5, maxAttempts: 5, message: 'x' });
  const armed = build({ server: { state: 'stopped', supervisor: sup(true) } });
  assert.equal(byId(armed, 'server.stop_retry').label, 'Stop Retrying');
  assert.equal(byId(armed, 'server.stop_retry').action.kind, 'server.stop_retry');
  assert.equal(byId(build({ server: { state: 'stopped', supervisor: sup(false) } }), 'server.stop_retry'), undefined);
});
