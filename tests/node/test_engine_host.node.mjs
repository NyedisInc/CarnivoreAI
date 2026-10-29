import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Module from 'node:module';
import { EventEmitter } from 'node:events';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const macDir = path.join(root, 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));
const host = (f) => require(path.join(macDir, 'engine-host', f));

const queue = [];
function t(name, fn) { queue.push([name, fn]); }
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'engine-host-'));

t('strategy: default detached, env, legacy env, unknown value warns and falls back, file source, env wins', () => {
  const { pickStrategy } = host('settings.js');
  assert.deepEqual(pickStrategy({ env: {} }), { name: 'detached', source: 'default', warning: null });
  assert.equal(pickStrategy({ env: { CARNIVORE_ENGINE_HOST: 'launchd-agent' } }).name, 'launchd-agent');
  assert.equal(pickStrategy({ env: { CLOUDE_ENGINE_HOST: 'child' } }).name, 'child');
  assert.equal(pickStrategy({ env: { CARNIVORE_ENGINE_HOST: 'child', CLOUDE_ENGINE_HOST: 'launchd-agent' } }).name, 'child');
  const bad = pickStrategy({ env: { CARNIVORE_ENGINE_HOST: 'systemd' } });
  assert.equal(bad.name, 'detached');
  assert.match(bad.warning, /unknown engine host "systemd"/);
  const ud = tmp();
  fs.writeFileSync(path.join(ud, 'engine-host.json'), JSON.stringify({ strategy: 'launchd-agent' }));
  assert.equal(pickStrategy({ env: {}, userData: ud }).name, 'launchd-agent');
  assert.equal(pickStrategy({ env: {}, userData: ud }).source, 'file');
  assert.equal(pickStrategy({ env: { CARNIVORE_ENGINE_HOST: 'child' }, userData: ud }).name, 'child');
  fs.writeFileSync(path.join(ud, 'engine-host.json'), '{not json');
  assert.equal(pickStrategy({ env: {}, userData: ud }).name, 'detached');
});

t('host: detached and launchd-agent survive a quit, child does not; setHostFromSettings logs the warning', () => {
  const { createEngineHost, setHostFromSettings, getHost } = host('index.js');
  assert.equal(createEngineHost({ name: 'detached' }).survivesQuit(), true);
  assert.equal(createEngineHost({ name: 'launchd-agent' }).survivesQuit(), true);
  assert.equal(createEngineHost({ name: 'child' }).survivesQuit(), false);
  const logs = [];
  setHostFromSettings({ env: { CARNIVORE_ENGINE_HOST: 'nope' }, log: (m) => logs.push(m) });
  assert.equal(getHost().name, 'detached');
  assert.equal(logs.length, 1);
  const status = getHost().status({ getState: () => 'running', ownedProcess: false, processPid: 7 });
  assert.deepEqual(status, { strategy: 'detached', state: 'running', owned: false, pid: 7, service: null });
  assert.equal(getHost().logPath({ logFile: '/x/logs/server.log' }), '/x/logs/server.log');
  assert.equal(getHost().serviceOwnsEngine(), false);
  assert.equal(createEngineHost({ name: 'launchd-agent', service: { isEnabled: () => true } }).serviceOwnsEngine(), true);
  assert.equal(createEngineHost({ name: 'launchd-agent', service: { isEnabled: () => false } }).serviceOwnsEngine(), false);
  assert.equal(createEngineHost({ name: 'detached', service: { isEnabled: () => true } }).serviceOwnsEngine(), false);
});

t('spawn: detached and launchd-agent spawn detached, child does not', () => {
  const { spawnEngine } = host('spawn.js');
  const seen = [];
  for (const strategy of ['detached', 'launchd-agent', 'child']) {
    const ud = tmp();
    const stub = { pid: 1, unref() {} };
    const orig = require('node:child_process').spawn;
    require('node:child_process').spawn = (cmd, args, opts) => { seen.push([strategy, opts.detached]); return stub; };
    try {
      spawnEngine(strategy, { pythonPath: 'py', cwd: ud, env: {}, logFile: path.join(ud, 'logs', 'server.log'),
        spawnImpl: strategy === 'child' ? undefined : (c, a, o) => { seen.push([strategy, o.detached]); return stub; } });
    } finally { require('node:child_process').spawn = orig; }
  }
  assert.deepEqual(seen, [['detached', true], ['launchd-agent', true], ['child', false]]);
});

t('plist: label, serviceName with .plist, headless argument, KeepAlive SuccessfulExit false, shipped under Contents/Library/LaunchAgents', () => {
  const c = host('constants.js');
  const plist = fs.readFileSync(c.SERVICE_PLIST_SOURCE, 'utf8');
  assert.equal(c.SERVICE_NAME, 'ai.carnivore.menubar.engine.plist');
  assert.match(plist, /<key>Label<\/key>\s*<string>ai\.carnivore\.menubar\.engine<\/string>/);
  assert.match(plist, /<string>--engine-service<\/string>/);
  assert.match(plist, /<key>BundleProgram<\/key>\s*<string>Contents\/MacOS\/Carnivore<\/string>/);
  assert.match(plist, /<key>KeepAlive<\/key>\s*<dict>\s*<key>SuccessfulExit<\/key>\s*<false\/>/);
  assert.match(plist, /<key>AssociatedBundleIdentifiers<\/key>\s*<array>\s*<string>ai\.carnivore\.menubar<\/string>/);
  const pkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
  const extra = pkg.build.mac.extraFiles.find((e) => e.from === 'engine-host/ai.carnivore.menubar.engine.plist');
  assert.equal(extra.to, 'Library/LaunchAgents/ai.carnivore.menubar.engine.plist');
});

t('service control: one agentService registration with the .plist name; status read back from the OS; kickstart -k and stop argv', async () => {
  const { createServiceControl } = host('service-control.js');
  const calls = [];
  let state = 'not-registered';
  const app = {
    getLoginItemSettings: (o) => { calls.push(['get', o]); return { status: state }; },
    setLoginItemSettings: (o) => { calls.push(['set', o]); state = o.openAtLogin ? 'enabled' : 'not-registered'; },
  };
  const execs = [];
  const svc = createServiceControl({ app, execFile: (cmd, args, cb) => { execs.push([cmd, ...args]); cb(null); }, uid: 501 });
  assert.equal(svc.isEnabled(), false);
  assert.equal(svc.register(), 'enabled');
  assert.deepEqual(calls.find((c) => c[0] === 'set')[1], { type: 'agentService', serviceName: 'ai.carnivore.menubar.engine.plist', openAtLogin: true });
  assert.equal(svc.isEnabled(), true);
  assert.equal(svc.unregister(), 'not-registered');
  assert.equal(await svc.kickstart(), true);
  assert.equal(await svc.kickstart(true), true);
  assert.equal(await svc.stop(), true);
  assert.deepEqual(execs, [['/bin/launchctl', 'kickstart', 'gui/501/ai.carnivore.menubar.engine'],
    ['/bin/launchctl', 'kickstart', '-k', 'gui/501/ai.carnivore.menubar.engine'], ['/bin/launchctl', 'stop', 'ai.carnivore.menubar.engine']]);
  const throwing = createServiceControl({ app: { getLoginItemSettings() { throw new Error('x'); } }, execFile() {}, uid: 1 });
  assert.equal(throwing.status(), 'unknown');
});

function loopRig({ running = '1.0.0', disk = '1.0.0', managerOver = {}, userData = tmp(), max } = {}) {
  const { START_FAILURE_FILE, START_FAILURE_WINDOW_MS, MAX_START_FAILURES } = host('service-loop.js');
  const { createRestartGuard } = host('version-guard.js');
  const { createServiceLoop } = host('service-loop.js');
  const events = [];
  const state = { disk };
  const manager = {
    getState: () => 'running', engineIsUp: async () => true, getHealth: async () => ({ version: running }),
    getBindReport: () => ({ setup_status: 'unpaired', bind: { restart_required: false } }),
    start: async () => { events.push('start'); }, restart: async () => { events.push('restart'); return { restarted: true }; },
    restartAdoptedEngine: async () => { events.push('restartAdopted'); }, ...managerOver,
  };
  const guard = createRestartGuard({ userData, max });
  const loop = createServiceLoop({
    manager, running, readDisk: () => state.disk, guard,
    decideRebind: require(path.join(macDir, 'rebind-after-pair.js')).decide,
    stopEngine: async () => { events.push('stopEngine'); }, exit: (code) => events.push(`exit:${code}`), log: () => {},
    startGuard: createRestartGuard({ userData, file: START_FAILURE_FILE, max: MAX_START_FAILURES, windowMs: START_FAILURE_WINDOW_MS }),
    sleep: async () => {}, healthWaitMs: 3000,
  });
  return { loop, events, state, guard, userData };
}

t('version: a newer bundle on disk stops the engine cleanly then exits NON-ZERO (KeepAlive restarts it)', async () => {
  const r = loopRig({ disk: '1.0.1' });
  assert.equal(await r.loop.tick(), 'exit-for-update');
  assert.deepEqual(r.events, ['stopEngine', 'exit:1']);
});

t('version: same version or an unreadable disk does nothing', async () => {
  const same = loopRig();
  assert.equal(await same.loop.tick(), 'ok');
  assert.deepEqual(same.events, []);
  const unreadable = loopRig({ disk: null });
  assert.equal(await unreadable.loop.tick(), 'ok');
  assert.deepEqual(unreadable.events, []);
});

t('version: the bound. A bundle that keeps disagreeing restarts three times, then the service holds still (no tight loop)', async () => {
  const ud = tmp();
  const outcomes = [];
  for (let i = 0; i < 5; i += 1) outcomes.push(await loopRig({ disk: '9.9.9', userData: ud }).loop.tick());
  assert.deepEqual(outcomes, ['exit-for-update', 'exit-for-update', 'exit-for-update', 'hold', 'hold']);
  const healthy = loopRig({ running: '9.9.9', disk: '9.9.9', userData: ud });
  assert.equal(await healthy.loop.tick(), 'ok');
  assert.equal(fs.existsSync(path.join(ud, 'engine-service-restarts.json')), false);
  assert.equal(await loopRig({ disk: '9.9.9', userData: ud }).loop.tick(), 'exit-for-update');
});

t('version: Info.plist parsing and the disk read', () => {
  const { parseBundleVersion, readDiskVersion } = host('version-guard.js');
  assert.equal(parseBundleVersion('<dict><key>CFBundleShortVersionString</key>\n<string>1.16.4</string></dict>'), '1.16.4');
  assert.equal(parseBundleVersion('bplist00'), null);
  const app = path.join(tmp(), 'Carnivore.app');
  fs.mkdirSync(path.join(app, 'Contents', 'MacOS'), { recursive: true });
  fs.writeFileSync(path.join(app, 'Contents', 'Info.plist'), '<key>CFBundleShortVersionString</key><string>2.0.0</string>');
  assert.equal(readDiskVersion({ exe: path.join(app, 'Contents', 'MacOS', 'Carnivore') }), '2.0.0');
  assert.equal(readDiskVersion({ exe: '/nonexistent/Carnivore.app/Contents/MacOS/Carnivore' }), null);
});

t('reopen: activate, open-file and open-url launch a second instance (open -n) and never create a window', () => {
  const { createReopenRouter, wireReopen } = host('reopen.js');
  const execs = [];
  const router = createReopenRouter({ execFile: (cmd, args, cb) => { execs.push([cmd, ...args]); cb(null); }, bundlePath: '/Applications/Carnivore.app' });
  const app = new EventEmitter();
  wireReopen({ app, router });
  app.emit('activate');
  let prevented = 0;
  app.emit('open-file', { preventDefault: () => { prevented += 1; } }, '/tmp/folder');
  router.flush();
  app.emit('open-url', { preventDefault: () => { prevented += 1; } }, 'carnivore://open');
  app.emit('open-url', { preventDefault: () => { prevented += 1; } }, 'https://evil.example/');
  assert.deepEqual(execs, [
    ['/usr/bin/open', '-n', '/Applications/Carnivore.app'],
    ['/usr/bin/open', '-n', '-a', '/Applications/Carnivore.app', '/tmp/folder'],
    ['/usr/bin/open', '-n', '-a', '/Applications/Carnivore.app', 'carnivore://open'],
  ]);
  assert.equal(router.onOpenFile('relative/or/-flag'), false);
  assert.equal(prevented, 3);
  const burst = [];
  let clock = 1000;
  let pending = null;
  const bursty = createReopenRouter({ execFile: (cmd, args, cb) => { burst.push(args); cb(null); }, bundlePath: '/Applications/Carnivore.app',
    now: () => clock, setTimer: (fn) => { pending = fn; return 1; } });
  for (let i = 0; i < 50; i += 1) bursty.onOpenFile(`/tmp/f${i}`);
  for (let i = 0; i < 50; i += 1) bursty.onOpenUrl(`carnivore://open?x=${i}`);
  for (let i = 0; i < 50; i += 1) bursty.onReopen();
  pending();
  assert.equal(burst.length, 3, 'one launch for the batched drop, one for the first link, one for the first reopen');
  assert.deepEqual(burst.find((a) => a.includes('/tmp/f0')).slice(3), ['/tmp/f0', '/tmp/f1', '/tmp/f2', '/tmp/f3', '/tmp/f4']);
  clock += 600;
  assert.equal(bursty.onOpenUrl('carnivore://open'), true, 'a link a full window later goes through');
  const dev = createReopenRouter({ execFile: () => assert.fail('no launch for a dev run'), bundlePath: null });
  assert.equal(dev.onReopen(), false);
  for (const f of ['reopen.js', 'service-entry.js', 'service-loop.js']) {
    const src = fs.readFileSync(path.join(macDir, 'engine-host', f), 'utf8').replace(/\/\/.*$/gm, '');
    assert.doesNotMatch(src, /BrowserWindow|appWindow|createAppWindow|new Tray\b/, `${f} must not create a window or tray`);
  }
});

t('service entry: argv switch, activation policy prohibited, no single-instance lock', () => {
  const entry = host('service-entry.js');
  const prohibited = [];
  const app = Object.assign(new EventEmitter(), {
    setActivationPolicy: (p) => prohibited.push(p), getPath: () => '/Applications/Carnivore.app/Contents/MacOS/Carnivore',
    whenReady: () => new Promise(() => {}), requestSingleInstanceLock() { assert.fail('the service takes no lock'); },
  });
  assert.equal(entry.runIfRequested({ app, argv: ['/x/Carnivore'] }), false);
  assert.deepEqual(prohibited, []);
  assert.equal(entry.runIfRequested({ app, argv: ['/x/Carnivore', '--engine-service'] }), true);
  assert.deepEqual(prohibited, ['prohibited']);
  assert.equal(entry.bundleOf('/Applications/Carnivore.app/Contents/MacOS/Carnivore'), '/Applications/Carnivore.app');
  const src = fs.readFileSync(path.join(macDir, 'engine-host', 'service-entry.js'), 'utf8');
  assert.match(src, /app\.on\('before-quit', \(event\) => \{ event\.preventDefault\(\); onTerm\(\); \}\)/);
  assert.equal(entry.bundleOf('/x/node_modules/electron/dist/Electron'), null);
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.ok(main.indexOf('engine-host/service-entry') < main.indexOf('requestSingleInstanceLock'), 'the service branch runs before the lock');
});

t('adopt: health first; the bind test only runs when nothing answered; the pid is the LISTEN row', async () => {
  const { probeEngine, listenPidCommand } = host('adopt.js');
  const order = [];
  const probes = (healthy, bound) => ({
    health: async () => { order.push('health'); return healthy ? { version: '1' } : null; },
    bind: async () => { order.push('bind'); return bound; },
    listenPid: async () => { order.push('pid'); return 4242; },
  });
  assert.deepEqual(await probeEngine(probes(true, false)), { up: true, via: 'health', health: { version: '1' }, pid: 4242 });
  assert.deepEqual(order, ['health', 'pid']);
  order.length = 0;
  assert.equal((await probeEngine(probes(false, true))).via, 'bind');
  assert.deepEqual(order, ['health', 'bind', 'pid']);
  order.length = 0;
  assert.deepEqual(await probeEngine(probes(false, false)), { up: false, via: 'none', health: null, pid: null });
  assert.match(listenPidCommand(8000), /-sTCP:LISTEN -t$/);
  const sm = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
  const up = sm.slice(sm.indexOf('async engineIsUp('), sm.indexOf('async engineIsUp(') + 400);
  const healthAt = up.indexOf('getHealth('), bindAt = up.indexOf('isPortInUse(');
  assert.ok(healthAt >= 0 && bindAt >= 0 && healthAt < bindAt, 'engineIsUp asks health before the bind test');
  assert.match(sm, /lsof -nP -iTCP:\$\{port\} -sTCP:LISTEN -t/);
  const probed = await require(path.join(macDir, 'engine-host', 'index.js')).createEngineHost({ name: 'detached' }).adopt({
    getHealth: async () => ({ version: '1' }), isPortInUse: async () => assert.fail('bind probe before health'),
    findPortHolderPid: async () => 99, getPort: () => 8000,
  });
  assert.equal(probed.pid, 99);
});

t('teardown: TERM on a window instance quits normally and touches no engine; TERM on the service stops the engine, then exits 0', async () => {
  const { installTermHandler } = host('teardown.js');
  const order = [];
  const win = new EventEmitter();
  installTermHandler({ proc: win, role: 'window', quit: () => order.push('quit'), stopEngine: () => order.push('WRONG-stop'), exit: () => order.push('WRONG-exit') });
  win.emit('SIGTERM'); win.emit('SIGTERM');
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(order, ['quit']);
  order.length = 0;
  const svc = new EventEmitter();
  installTermHandler({ proc: svc, role: 'service', quit: () => order.push('WRONG-quit'),
    stopEngine: async () => { await new Promise((r) => setTimeout(r, 20)); order.push('stopEngine'); }, exit: (c) => order.push(`exit:${c}`) });
  svc.emit('SIGTERM');
  await new Promise((r) => setTimeout(r, 80));
  assert.deepEqual(order, ['stopEngine', 'exit:0']);
  order.length = 0;
  const failing = new EventEmitter();
  installTermHandler({ proc: failing, role: 'service', quit() {}, stopEngine: async () => { throw new Error('boom'); }, exit: (c) => order.push(`exit:${c}`), log: () => {} });
  failing.emit('SIGTERM');
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(order, ['exit:0']);
});

t('rebind: the service loop finishes the first-run rebind once, on the report the window would have read', async () => {
  const report = { setup_status: 'complete', bind: { restart_required: true, effective_host: '127.0.0.1' } };
  const r = loopRig({ managerOver: { getBindReport: () => report } });
  assert.equal(await r.loop.tick(), 'rebind');
  assert.equal(await r.loop.tick(), 'ok');
  assert.deepEqual(r.events, ['restart']);
  const notYet = loopRig({ managerOver: { getBindReport: () => ({ setup_status: 'incomplete', bind: { restart_required: true } }) } });
  assert.equal(await notYet.loop.tick(), 'ok');
  assert.deepEqual(notYet.events, []);
  const adopted = loopRig({ managerOver: { adoptedVersion: '1.0.0', getBindReport: () => report, restart: async () => ({ refused: true }) } });
  assert.equal(await adopted.loop.tick(), 'rebind');
  assert.deepEqual(adopted.events, ['restartAdopted']);
});

t('loop: an engine that is not there is started; a refused adoption waits and never replaces the holder; five failed starts exit 0 (stay down)', async () => {
  const down = loopRig({ managerOver: { getState: () => 'stopped', engineIsUp: async () => false } });
  assert.equal(await down.loop.tick(), 'started');
  assert.deepEqual(down.events, ['start']);
  const refused = loopRig({ managerOver: { getState: () => 'stopped', start: async () => { const e = new Error('x'); e.code = 'ADOPTION_REFUSED'; e.outcome = 'version-mismatch'; throw e; } } });
  assert.equal(await refused.loop.tick(), 'ok');
  assert.deepEqual(refused.events, []);
  const broken = loopRig({ managerOver: { getState: () => 'stopped', start: async () => { throw new Error('no python'); } } });
  const results = [];
  for (let i = 0; i < 5; i += 1) results.push(await broken.loop.tick());
  assert.equal(results[4], 'exit-start-failures');
  assert.deepEqual(broken.events, ['exit:0']);
});

t('loop: an engine that dies right after it spawns counts as a failed start, survives a launchd restart, and ends in a clean exit 0 (review S2)', async () => {
  const ud = tmp();
  const dying = { getState: () => 'stopped', engineIsUp: async () => false, getHealth: async () => null };
  const results = [];
  for (let i = 0; i < 5; i += 1) {
    const r = loopRig({ userData: ud, managerOver: { ...dying, start: async () => { r.events.push('start'); } } });
    results.push([await r.loop.tick(), r.events.join(',')]);
  }
  assert.deepEqual(results.slice(0, 4).map((x) => x[0]), ['ok', 'ok', 'ok', 'ok']);
  assert.deepEqual(results[4], ['exit-start-failures', 'start,exit:0']);
  const after = loopRig({ userData: ud, managerOver: { ...dying, start: async () => assert.fail('the spent bound must not spawn again') } });
  assert.equal(await after.loop.tick(), 'exit-start-failures');
  assert.deepEqual(after.events, ['exit:0']);
  const healthy = tmp();
  for (let i = 0; i < 3; i += 1) await loopRig({ userData: healthy, managerOver: { ...dying, start: async () => {} } }).loop.tick();
  let up = false;
  const good = loopRig({ userData: healthy, managerOver: { getState: () => (up ? 'running' : 'stopped'), engineIsUp: async () => up, start: async () => { up = true; }, getHealth: async () => (up ? { version: '1.0.0' } : null) } });
  assert.equal(await good.loop.tick(), 'started');
  assert.equal(fs.existsSync(path.join(healthy, 'engine-service-start-failures.json')), false);
});

function toggleRig() {
  const dir = tmp();
  const installer = { on: false, isEnabled() { return this.on; }, enable() { this.on = true; }, disable() { this.on = false; } };
  const service = { on: false, isEnabled() { return this.on; }, register() { this.on = true; return 'enabled'; }, unregister() { this.on = false; return 'not-registered'; } };
  return { dir, installer, service };
}

t('toggles under detached are exactly today: engine = the LaunchAgent, background stays null', () => {
  const { readLogin, setLogin } = require(path.join(macDir, 'login-items.js'));
  const { dir, installer } = toggleRig();
  assert.deepEqual(readLogin({ installer, dir }), { engine: false, window: false, background: null });
  assert.deepEqual(setLogin({ installer, launchArgs: () => [], dir, which: 'engine', enabled: true }), { engine: true, window: false, background: null });
  assert.deepEqual(setLogin({ installer, launchArgs: () => [], dir, which: 'background', enabled: true }), { engine: true, window: false, background: null });
});

t('toggles under launchd-agent: 1 is the service, 2 the LaunchAgent that opens the app, 3 the window flag and needs 2', () => {
  const { readLogin, setLogin } = require(path.join(macDir, 'login-items.js'));
  const { dir, installer, service } = toggleRig();
  const set = (which, enabled) => setLogin({ installer, service, launchArgs: () => [], dir, which, enabled });
  assert.deepEqual(readLogin({ installer, service, dir }), { engine: false, window: false, background: false });
  assert.deepEqual(set('engine', true), { engine: true, window: false, background: false });
  assert.equal(installer.on, false);
  assert.deepEqual(set('background', true), { engine: true, window: false, background: true });
  assert.deepEqual(set('window', true), { engine: true, window: true, background: true });
  assert.deepEqual(set('background', false), { engine: true, window: false, background: false });
  assert.deepEqual(set('window', true), { engine: true, window: true, background: true });
  assert.deepEqual(set('engine', false), { engine: false, window: true, background: true });
  assert.equal(service.on, false);
});

t('tray row: the installer itself under detached, the service under launchd-agent', () => {
  const { trayLogin } = host('tray-login.js');
  const { installer, service } = toggleRig();
  assert.equal(trayLogin({ strategy: 'detached', installer, service }), installer);
  const row = trayLogin({ strategy: 'launchd-agent', installer, service });
  assert.equal(row.isEnabled(), false);
  row.toggle();
  assert.equal(service.on, true);
  assert.equal(row.isEnabled(), true);
  assert.equal(installer.on, false);
  row.toggle();
  assert.equal(service.on, false);
});

function syncRig({ launchAtLogin = true }) {
  const userData = tmp();
  const installer = { on: launchAtLogin, dropped: 0, isEnabled() { return this.on; }, dropPlistFile() { this.dropped += 1; } };
  return { userData, installer };
}

t('carriedBy is written only after the OS reports the service enabled', () => {
  const { syncLogin } = host('login-sync.js');
  const { readRecord } = require(path.join(macDir, 'engine', 'login-handoff.js'));
  const early = syncRig({ launchAtLogin: true });
  let early_regs = 0;
  syncLogin({ strategy: 'launchd-agent', userData: early.userData, installer: early.installer, service: { register: () => { early_regs += 1; return 'enabled'; } }, fresh: false, windowAtLogin: false, recordOnly: true });
  assert.equal(early_regs, 0);
  assert.equal(readRecord(early.userData).launchAtLogin, true);
  const a = syncRig({ launchAtLogin: true });
  const pending = { register: () => 'requires-approval', status: () => 'requires-approval' };
  const first = syncLogin({ strategy: 'launchd-agent', userData: a.userData, installer: a.installer, service: pending, fresh: false, windowAtLogin: false });
  assert.equal(first.registered, true);
  assert.equal(readRecord(a.userData).carriedBy, null);
  const enabled = { register: () => 'enabled' };
  syncLogin({ strategy: 'launchd-agent', userData: a.userData, installer: a.installer, service: enabled, fresh: false, windowAtLogin: false });
  assert.equal(readRecord(a.userData).carriedBy, 'R2-06');
  let again = 0;
  syncLogin({ strategy: 'launchd-agent', userData: a.userData, installer: a.installer, service: { register: () => { again += 1; return 'enabled'; } }, fresh: false, windowAtLogin: false });
  assert.equal(again, 0);
  const off = syncRig({ launchAtLogin: false });
  let regs = 0;
  const counting = { register: () => { regs += 1; return 'enabled'; } };
  syncLogin({ strategy: 'launchd-agent', userData: off.userData, installer: off.installer, service: counting, fresh: false, windowAtLogin: false });
  assert.equal(regs, 0);
  assert.equal(readRecord(off.userData).carriedBy, null);
  const fresh = syncRig({ launchAtLogin: false });
  syncLogin({ strategy: 'launchd-agent', userData: fresh.userData, installer: fresh.installer, service: counting, fresh: true, windowAtLogin: false });
  assert.equal(regs, 1);
  assert.equal(readRecord(fresh.userData).carriedBy, 'R2-06');
});

t('the LaunchAgent plist is removed only under launchd-agent, only once carried, and not while toggle 2 should keep it', () => {
  const { syncLogin } = host('login-sync.js');
  const enabled = { register: () => 'enabled' };
  const d = syncRig({ launchAtLogin: false });
  syncLogin({ strategy: 'launchd-agent', userData: d.userData, installer: d.installer, service: enabled, fresh: true, windowAtLogin: false });
  const dropsBefore = d.installer.dropped;
  const detached = syncLogin({ strategy: 'detached', userData: d.userData, installer: d.installer, service: null, fresh: false, windowAtLogin: false });
  assert.equal(detached.retired.reason, 'login-service-not-ready');
  assert.equal(d.installer.dropped, dropsBefore);
  assert.equal(dropsBefore, 1);
  const keep = syncRig({ launchAtLogin: true });
  const kept = syncLogin({ strategy: 'launchd-agent', userData: keep.userData, installer: keep.installer, service: enabled, fresh: false, windowAtLogin: false });
  assert.equal(kept.retired.reason, 'background-toggle-on');
  assert.equal(keep.installer.dropped, 0);
  const pend = syncRig({ launchAtLogin: false });
  const pending = syncLogin({ strategy: 'launchd-agent', userData: pend.userData, installer: pend.installer, service: { register: () => 'requires-approval' }, fresh: true, windowAtLogin: false });
  assert.equal(pending.retired.reason, 'not-carried');
  assert.equal(pend.installer.dropped, 0);
  const handoff = require(path.join(macDir, 'engine', 'login-handoff.js'));
  assert.equal(handoff.LOGIN_SERVICE_READY, false);
  assert.equal(host('constants.js').loginServiceReady('detached'), false);
  assert.equal(host('constants.js').loginServiceReady('launchd-agent'), true);
});

t('launchd-agent: a window with no engine kickstarts the service and waits; an older engine is kickstarted; stop goes through the service', async () => {
  const strategy = require(path.join(macDir, 'engine-host', 'strategies', 'launchd-agent.js'));
  const events = [];
  let up = false;
  const manager = {
    getBundleVersion: () => '2.0.0', getHealth: async () => (up ? { version: '2.0.0' } : null),
    start: async () => { events.push('manager.start'); }, engineIsUp: async () => up, stopEngine: async () => { events.push('route-stop'); return { stopped: true, via: 'route' }; },
  };
  const service = { isEnabled: () => true, kickstart: async (kill) => { events.push(kill ? 'kickstart-k' : 'kickstart'); up = true; return true; }, stop: async () => { events.push('service.stop'); up = false; return true; } };
  const ctx = { service, log: () => {}, sleep: async () => {}, waitMs: 50, verifyHolder: async () => null };
  await strategy.start(manager, ctx);
  assert.deepEqual(events, ['kickstart', 'manager.start']);
  events.length = 0;
  manager.getHealth = async () => ({ version: '1.9.0' });
  await strategy.start(manager, ctx);
  assert.equal(events[0], 'kickstart-k');
  events.length = 0;
  up = true;
  const stopped = await strategy.stop(manager, {}, ctx);
  assert.equal(stopped.via, 'service');
  assert.deepEqual(events, ['service.stop']);
  events.length = 0;
  const unregistered = await strategy.stop(manager, {}, { ...ctx, service: { isEnabled: () => false } });
  assert.equal(unregistered.via, 'route');
  const noService = await strategy.start({ ...manager, getHealth: async () => null, start: async () => events.push('plain-start') }, { ...ctx, service: null });
  assert.equal(noService, 2);
});

t('review B1: toggle 2 turned on after the service carried a fresh install survives the next launch', () => {
  const { syncLogin } = host('login-sync.js');
  const r = syncRig({ launchAtLogin: false });
  const args = { strategy: 'launchd-agent', userData: r.userData, installer: r.installer, service: { register: () => 'enabled' }, fresh: true, windowAtLogin: false };
  syncLogin(args);
  assert.equal(r.installer.dropped, 1);
  r.installer.on = true;
  const again = syncLogin({ ...args, fresh: false });
  assert.equal(r.installer.dropped, 1);
  assert.equal(again.retired.retired, false);
});

t('review S4: the previous choice is frozen at the first launchd-agent launch, so toggle 2 never turns toggle 1 on', () => {
  const { syncLogin } = host('login-sync.js');
  const r = syncRig({ launchAtLogin: false });
  let regs = 0;
  const args = { strategy: 'launchd-agent', userData: r.userData, installer: r.installer, service: { register: () => { regs += 1; return 'enabled'; } }, fresh: false, windowAtLogin: false };
  syncLogin(args);
  r.installer.on = true;
  syncLogin(args);
  assert.equal(regs, 0);
  const up = syncRig({ launchAtLogin: true });
  syncLogin({ strategy: 'detached', userData: up.userData, installer: up.installer, service: null, fresh: false, windowAtLogin: false });
  syncLogin({ ...args, userData: up.userData, installer: up.installer });
  assert.equal(regs, 1);
});

t('review S1: the second syncLogin never aborts the engine start; a failed record write only warns', () => {
  const { syncLogin, syncLoginSafe } = host('login-sync.js');
  const blocker = path.join(tmp(), 'file');
  fs.writeFileSync(blocker, 'x');
  const args = { strategy: 'detached', userData: path.join(blocker, 'sub'), installer: { isEnabled: () => false }, service: null, fresh: false, windowAtLogin: false };
  assert.throws(() => syncLogin(args));
  const warned = [];
  assert.equal(syncLoginSafe(args, (m) => warned.push(m)), null);
  assert.equal(warned.length, 1);
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /syncLoginSafe\(loginSyncArgs\(\)[^\n]*\);[^\n]*\n\s*await engineHostModule\.getHost\(\)\.start\(serverManager\)/);
});

t('#2440: a launch that reads detached unregisters a registered login service (logged); a failed unregister keeps launchd-agent; child is left alone', () => {
  const { setHostFromSettings } = host('index.js');
  const logs = [];
  const calls = [];
  let enabled = true;
  const svc = { isEnabled: () => enabled, unregister: () => { calls.push('unregister'); enabled = false; return 'not-registered'; }, kickstart: () => calls.push('WRONG-kickstart') };
  const h = setHostFromSettings({ env: { CARNIVORE_ENGINE_HOST: 'detached' }, service: svc, log: (m) => logs.push(m) });
  assert.equal(h.name, 'detached');
  assert.equal(h.serviceOwnsEngine(), false);
  assert.deepEqual(calls, ['unregister']);
  assert.ok(logs.some((m) => /unregistered/.test(m)));
  setHostFromSettings({ env: { CARNIVORE_ENGINE_HOST: 'detached' }, service: svc });
  assert.deepEqual(calls, ['unregister']);
  const stuck = { isEnabled: () => true, unregister: () => { throw new Error('denied'); } };
  assert.equal(setHostFromSettings({ env: { CARNIVORE_ENGINE_HOST: 'detached' }, service: stuck, log: () => {} }).name, 'launchd-agent');
  assert.equal(setHostFromSettings({ env: { CARNIVORE_ENGINE_HOST: 'detached' }, service: { isEnabled: () => true, unregister: () => 'enabled' }, log: () => {} }).name, 'launchd-agent');
  assert.equal(setHostFromSettings({ env: {} }).name, 'detached');
  assert.equal(setHostFromSettings({ env: { CARNIVORE_ENGINE_HOST: 'launchd-agent' }, service: { isEnabled: () => true, unregister: () => assert.fail('unregistered under launchd-agent') } }).name, 'launchd-agent');
  const on = { isEnabled: () => true, unregister: () => assert.fail('unregistered under child') };
  assert.equal(setHostFromSettings({ env: { CARNIVORE_ENGINE_HOST: 'child' }, service: on }).name, 'child');
});

t('#2441: SIGTERM on a window instance marks the quit as the system\'s before it quits, so the first-quit notice cannot block it; the service never shows it', async () => {
  const { installTermHandler } = host('teardown.js');
  const { quitPlan } = require(path.join(macDir, 'app-lifecycle-policy.js'));
  const order = [];
  const win = new EventEmitter();
  let systemQuit = false;
  installTermHandler({ proc: win, role: 'window', quit: () => order.push(`quit:system=${systemQuit}`), onSignal: () => { systemQuit = true; } });
  win.emit('SIGTERM');
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(order, ['quit:system=true']);
  assert.equal(quitPlan({ intent: 'app', noticeShown: false, engineSurvivesQuit: true, systemQuit }).showNotice, false);
  assert.equal(quitPlan({ intent: 'app', noticeShown: false, engineSurvivesQuit: true, systemQuit: false }).showNotice, true);
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /role: 'window'[^\n]*onSignal: \(\) => \{ systemQuit = true; \}/);
  const entry = fs.readFileSync(path.join(macDir, 'engine-host', 'service-entry.js'), 'utf8');
  assert.doesNotMatch(entry, /quit-notice|showMessageBox|dialog/);
});

t('#2442: a window whose ADOPTED engine dies while the login service owns it stays down; it still restarts one it spawned itself or without a service', () => {
  const real = Module._load;
  Module._load = function load(request, ...rest) { return request === 'electron' ? { app: { isPackaged: false, getPath: () => os.tmpdir(), getVersion: () => '0' } } : real.call(this, request, ...rest); };
  let ServerManager;
  try { ServerManager = require(path.join(macDir, 'server-manager.js')); } finally { Module._load = real; }
  const downs = [];
  const mk = (owned, serviceOwns) => {
    const m = new ServerManager();
    m.state = 'running'; m.ownedProcess = owned; m.serviceOwnsEngine = () => serviceOwns;
    m.superviseDown = (event) => downs.push(event);
    return m;
  };
  const quiet = console.log; console.log = () => {};
  try {
    const adopted = mk(false, true);
    adopted.superviseTick(false);
    assert.equal(downs.length, 0);
    assert.equal(adopted.state, 'stopped');
    mk(true, true).superviseTick(false);
    mk(false, false).superviseTick(false);
    assert.equal(downs.length, 2);
  } finally { console.log = quiet; }
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /serverManager\.serviceOwnsEngine = \(\) => engineHostModule\.getHost\(\)\.serviceOwnsEngine\(\)/);
});

t('a health miss while a deliberate stop is in flight is not an unexpected death: the supervisor does not restart (#2503)', () => {
  const real = Module._load;
  Module._load = function load(request, ...rest) { return request === 'electron' ? { app: { isPackaged: false, getPath: () => os.tmpdir(), getVersion: () => '0' } } : real.call(this, request, ...rest); };
  let ServerManager;
  try { ServerManager = require(path.join(macDir, 'server-manager.js')); } finally { Module._load = real; }
  const downs = [];
  const m = new ServerManager();
  m.state = 'running'; m.ownedProcess = true; m.superviseDown = (event) => downs.push(event);
  const quiet = console.log; console.log = () => {};
  try {
    m.stopRequested = true;
    m.superviseTick(false);
    assert.equal(downs.length, 0);
    assert.equal(m.state, 'running');
    m.stopRequested = false;
    m.superviseTick(false);
    assert.equal(downs.length, 1);
  } finally { console.log = quiet; }
});

t('review S2 (#2440): only an explicit detached unregisters the service; a missing, unknown or unreadable setting keeps it; a switch-back clears carriedBy', () => {
  const { setHostFromSettings } = host('index.js');
  const handoff = require(path.join(macDir, 'engine', 'login-handoff.js'));
  const svc = () => { const c = []; return { c, isEnabled: () => true, unregister: () => { c.push('unregister'); return 'x'; } }; };
  for (const env of [{}, { CARNIVORE_ENGINE_HOST: 'detatched' }]) {
    const s = svc();
    assert.equal(setHostFromSettings({ env, service: s, log: () => {} }).name, 'launchd-agent');
    assert.deepEqual(s.c, []);
  }
  const ud = tmp();
  fs.writeFileSync(path.join(ud, 'engine-host.json'), '{"strategy": "detac');
  const s2 = svc();
  assert.equal(setHostFromSettings({ env: {}, userData: ud, service: s2, log: () => {} }).name, 'launchd-agent');
  assert.deepEqual(s2.c, []);
  fs.writeFileSync(path.join(ud, 'engine-host.json'), '{"strategy":"detached"}');
  fs.writeFileSync(path.join(ud, handoff.RECORD_FILE), JSON.stringify({ launchAtLogin: true, windowAtLogin: false, carriedBy: 'r2-06' }));
  const s3 = svc(); let on = true; s3.isEnabled = () => on; s3.unregister = () => { on = false; s3.c.push('unregister'); return 'x'; };
  assert.equal(setHostFromSettings({ env: {}, userData: ud, service: s3, log: () => {} }).name, 'detached');
  assert.deepEqual(s3.c, ['unregister']);
  assert.equal(handoff.readRecord(ud).carriedBy, null);
});

t('review S1 (#2442): after an adopted service engine goes quiet the window re-adopts through start() once it answers, and not before', async () => {
  const real = Module._load;
  Module._load = function load(request, ...rest) { return request === 'electron' ? { app: { isPackaged: false, getPath: () => os.tmpdir(), getVersion: () => '0' } } : real.call(this, request, ...rest); };
  let ServerManager;
  try { ServerManager = require(path.join(macDir, 'server-manager.js')); } finally { Module._load = real; }
  const m = new ServerManager();
  m.state = 'running'; m.ownedProcess = false; m.serviceOwnsEngine = () => true;
  let healthy = false; let starts = 0;
  const { watchForService } = host('service-watch.js');
  m.getHealth = async () => (healthy ? { ok: 1 } : null);
  m.start = async () => { starts++; };
  const quiet = console.log; console.log = () => {};
  try { m.superviseTick(false); } finally { console.log = quiet; }
  assert.equal(await watchForService(m), false);
  assert.equal(starts, 0);
  healthy = true;
  assert.equal(await watchForService(m), true);
  assert.equal(await watchForService(m), false);
  assert.equal(starts, 1);
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /watchForService\(serverManager\)/);
});

t('review S6: the docs do not claim a window never starts a second engine', () => {
  const doc = fs.readFileSync(path.join(root, 'docs', 'reboot-restore.md'), 'utf8');
  assert.doesNotMatch(doc, /never starts a second engine/);
});

t('R2-BR N2: an unknown strategy string is capped at 64 characters and JSON-quoted in the warning', () => {
  const { pickStrategy } = host('settings.js');
  const bad = pickStrategy({ env: { CARNIVORE_ENGINE_HOST: `x\nforged log line${'y'.repeat(200)}` } });
  assert.ok(!bad.warning.includes('\n'), 'a newline never reaches the log line');
  assert.ok(bad.warning.length < 160, `capped (${bad.warning.length})`);
  assert.match(bad.warning, /unknown engine host "x\\nforged/);
});

t('R2-BR N3: a firstAt in the future counts as expired, so the bound cannot be held spent forever', () => {
  const { createRestartGuard } = host('version-guard.js');
  const userData = tmp();
  let clock = 10_000_000;
  const guard = createRestartGuard({ userData, max: 1, now: () => clock });
  guard.record('2.0.0');
  assert.equal(guard.allow('2.0.0'), false, 'spent inside the window');
  clock -= 3_600_000;
  assert.equal(guard.allow('2.0.0'), true, 'a negative age is expired');
});

t('R2-BR N4: an older-version listener restarts the service only when the same-user check passes, once per version', async () => {
  const strategy = require(path.join(macDir, 'engine-host', 'strategies', 'launchd-agent.js'));
  const { createRestartGuard } = host('version-guard.js');
  const events = [];
  const manager = { getBundleVersion: () => '2.0.0', getHealth: async () => ({ version: '1.9.0' }), start: async () => { events.push('manager.start'); } };
  const service = { isEnabled: () => true, kickstart: async () => { events.push('kickstart-k'); return true; } };
  const base = { service, log: () => {}, sleep: async () => {}, waitMs: 5 };
  await strategy.start(manager, { ...base, verifyHolder: async () => ({ reason: 'not_yours' }) });
  assert.deepEqual(events, ['manager.start'], 'an untrusted listener never causes a kickstart');
  events.length = 0;
  const kickstartGuard = createRestartGuard({ userData: tmp(), file: 'k.json', max: 1, windowMs: 30 * 60 * 1000 });
  const ok = { ...base, verifyHolder: async () => null, kickstartGuard };
  await strategy.start(manager, ok);
  await strategy.start(manager, ok);
  assert.deepEqual(events, ['kickstart-k', 'manager.start', 'manager.start'], 'the second window launch for the same version is bounded');
});

t('R2-HYGIENE 1: a non-string reported version never earns a kickstart, and alternating versions keep each one bounded', async () => {
  const strategy = require(path.join(macDir, 'engine-host', 'strategies', 'launchd-agent.js'));
  const { createRestartGuard } = host('version-guard.js');
  const events = [];
  let reported = { a: 1 };
  const manager = { getBundleVersion: () => '2.0.0', getHealth: async () => ({ version: reported }), start: async () => { events.push('manager.start'); } };
  const service = { isEnabled: () => true, kickstart: async () => { events.push('kickstart'); return true; } };
  const kickstartGuard = createRestartGuard({ userData: tmp(), file: 'k.json', max: 1, windowMs: 30 * 60 * 1000 });
  const ctx = { service, log: () => {}, sleep: async () => {}, waitMs: 5, verifyHolder: async () => null, kickstartGuard };
  for (const bad of [{ a: 1 }, ['1.9.0'], 190, 'x'.repeat(65)]) {
    reported = bad;
    await strategy.start(manager, ctx);
  }
  assert.deepEqual(events.filter((e) => e === 'kickstart'), [], 'an unusable version shape never restarts the service');
  for (const v of ['1.9.0', '1.8.0', '1.9.0', '1.8.0']) {
    reported = v;
    await strategy.start(manager, ctx);
  }
  assert.equal(events.filter((e) => e === 'kickstart').length, 2, 'each version restarts the service once, however the versions alternate');
});

t('R2-HYGIENE V1: a version named __proto__ is counted and bounded like any other string', () => {
  const { createRestartGuard } = host('version-guard.js');
  const guard = createRestartGuard({ userData: tmp(), file: 'p.json', max: 1, windowMs: 30 * 60 * 1000 });
  assert.equal(guard.allow('__proto__'), true);
  assert.equal(guard.record('__proto__'), 1);
  assert.equal(guard.allow('__proto__'), false, 'the count for __proto__ persisted');
  assert.equal(guard.record('1.9.0'), 1);
  assert.equal(guard.allow('__proto__'), false, 'another version does not disturb it');
});

t('R2-HYGIENE 3: the port-holder diagnostic asks for the LISTEN row through findPortHolderPid, not a bare lsof -ti', () => {
  const src = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
  const body = src.slice(src.indexOf('  describePortHolder() {'));
  const method = body.slice(0, body.indexOf('\n  }\n'));
  assert.doesNotMatch(method, /lsof -ti/, 'a bare -ti names connected clients too');
  assert.match(method, /this\.findPortHolderPid\(/);
  assert.doesNotMatch(src, /lsof -ti/);
});

t('size: main.js and server-manager.js did not grow; new files stay under 500 lines; no em or en dash', () => {
  const lines = (f) => fs.readFileSync(f, 'utf8').split('\n').length - 1;
  assert.ok(lines(path.join(macDir, 'main.js')) <= 973, 'main.js must not grow');
  assert.ok(lines(path.join(macDir, 'server-manager.js')) <= 1848, 'server-manager.js must not grow');
  const files = [];
  const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : files.push(path.join(d, e.name))));
  walk(path.join(macDir, 'engine-host'));
  assert.ok(files.length >= 14);
  for (const f of files) {
    assert.ok(lines(f) < 500, `${f} is ${lines(f)} lines`);
    assert.doesNotMatch(fs.readFileSync(f, 'utf8'), /[\u2013\u2014]/, `${f} holds a dash that is not a hyphen`);
  }
});

t('round 2 D1: an explicit detached run then a switch back to launchd-agent registers the service again with no LaunchAgent plist; a System Settings disable does not', () => {
  const { syncLogin } = host('login-sync.js');
  const { setHostFromSettings } = host('index.js');
  const { readRecord } = require(path.join(macDir, 'engine', 'login-handoff.js'));
  const r = syncRig({ launchAtLogin: false });
  let regs = 0; let on = false;
  const service = { register: () => { regs += 1; on = true; return 'enabled'; }, unregister: () => { on = false; return 'notRegistered'; }, isEnabled: () => on };
  const args = { strategy: 'launchd-agent', userData: r.userData, installer: r.installer, service, fresh: true, windowAtLogin: false };
  syncLogin(args);
  assert.equal(regs, 1);
  syncLogin({ ...args, fresh: false });
  on = false;
  syncLogin({ ...args, fresh: false });
  assert.equal(regs, 1);
  fs.writeFileSync(path.join(r.userData, 'engine-host.json'), '{"strategy":"detached"}');
  on = true;
  assert.equal(setHostFromSettings({ env: {}, userData: r.userData, service, log: () => {} }).name, 'detached');
  assert.equal(on, false);
  assert.equal(readRecord(r.userData).carriedBy, null);
  syncLogin({ strategy: 'detached', userData: r.userData, installer: r.installer, service: null, fresh: false, windowAtLogin: false });
  fs.writeFileSync(path.join(r.userData, 'engine-host.json'), '{"strategy":"launchd-agent"}');
  syncLogin({ ...args, fresh: false });
  assert.equal(regs, 2);
  assert.equal(readRecord(r.userData).carriedBy, 'R2-06');
  assert.equal(readRecord(r.userData).switchedBack, undefined);
  syncLogin({ ...args, fresh: false });
  assert.equal(regs, 2);
});

t('P11 (#2454): a same-user other-version holder is never stopped; one log line, a retry about a minute apart, no exit; when it leaves the next retry starts', async () => {
  let clock = 0; let starts = 0; let stops = 0; let exits = 0; let holderGone = false; let up = false; const lines = []; const startAt = [];
  const { createServiceLoop, REPLACE_BACKOFF_MS, MISMATCH_RELOG_MS } = host('service-loop.js');
  const { createRestartGuard } = host('version-guard.js');
  const startGuard = createRestartGuard({ userData: tmp(), file: 'f.json', max: 5, windowMs: 1800000 });
  const loop = createServiceLoop({ manager: { getState: () => (up ? 'running' : 'stopped'), engineIsUp: async () => up, getHealth: async () => ({ version: '1.0.0' }),
    getBindReport: () => ({ setup_status: 'unpaired', bind: { restart_required: false } }),
    start: async () => { starts += 1; startAt.push(clock); if (holderGone) up = true; else { const e = new Error('refused'); e.code = 'ADOPTION_REFUSED'; e.outcome = 'version-mismatch'; e.pid = 111; throw e; } },
    restartAdoptedEngine: async () => { stops += 1; }, stopEngine: async () => { stops += 1; } },
    running: '1.0.0', readDisk: () => '1.0.0', guard: createRestartGuard({ userData: tmp() }), decideRebind: () => 'none', stopEngine: async () => { stops += 1; },
    startGuard, exit: () => { exits += 1; }, log: (m) => lines.push(m), now: () => clock, sleep: async () => {}, healthWaitMs: 1000 });
  for (let i = 0; i < 40; i += 1) { await loop.tick(); clock += 15000; }
  assert.equal(stops, 0, 'the service must not stop the holder');
  assert.equal(exits, 0, 'refusals never count toward the five-failure exit');
  assert.equal(lines.filter((l) => l.includes('version-mismatch')).length, 1, `lines: ${lines.join(' | ')}`);
  assert.ok(starts >= 8 && starts <= 12, `start attempts: ${starts}`);
  for (let i = 1; i < startAt.length; i += 1) assert.ok(startAt[i] - startAt[i - 1] >= REPLACE_BACKOFF_MS, 'retries are spaced a minute apart');
  assert.ok(REPLACE_BACKOFF_MS < MISMATCH_RELOG_MS);
  assert.equal(startGuard.allow('1.0.0'), true, 'no failure was recorded');
  holderGone = true;
  clock += 60000;
  const before = starts;
  await loop.tick();
  assert.equal(starts, before + 1, 'the next retry starts or adopts as normal');
  assert.equal(stops, 0);
});

t('proof 4: a port holder that is not provably this user\'s own is waited out, never counted toward the exit-0 bound (docs: never gives up)', async () => {
  let clock = 0; let starts = 0; let exits = 0; const lines = []; let holderGone = false;
  const { createServiceLoop } = host('service-loop.js');
  const { createRestartGuard } = host('version-guard.js');
  const guardDir = tmp();
  const startGuard = createRestartGuard({ userData: guardDir, file: 'f.json', max: 5, windowMs: 1800000 });
  const loop = createServiceLoop({ manager: { getState: () => (holderGone ? 'running' : 'stopped'), engineIsUp: async () => holderGone, getHealth: async () => ({ version: '1.0.0' }),
    getBindReport: () => ({ setup_status: 'unpaired', bind: { restart_required: false } }),
    start: async () => { starts += 1; if (!holderGone) { const e = new Error('Another program holds port 8000 and Carnivore could not confirm it is yours.'); e.code = 'PORT_HOLDER_NOT_YOURS'; throw e; } } },
    running: '1.0.0', readDisk: () => '1.0.0', guard: createRestartGuard({ userData: tmp() }), decideRebind: () => 'none', stopEngine: async () => {},
    startGuard, exit: () => { exits += 1; }, log: (m) => lines.push(m), now: () => clock, sleep: async () => {}, healthWaitMs: 1000 });
  for (let i = 0; i < 40; i += 1) { await loop.tick(); clock += 15000; }
  assert.equal(exits, 0, 'the service must not exit 0 and stay down');
  assert.ok(starts >= 8 && starts <= 12, `start attempts: ${starts}`);
  assert.ok(lines.length <= 2, `lines: ${lines.length}`);
  assert.equal(startGuard.allow('1.0.0'), true, 'no failure was recorded');
  holderGone = true;
  clock += 60000;
  await loop.tick();
  assert.equal(exits, 0);
});

t('proof 4b: a non-Carnivore port holder (plain refusal from start()) is waited out, never counted toward the exit-0 bound (docs: never gives up)', async () => {
  let clock = 0; let starts = 0; let exits = 0; const lines = []; let holderGone = false;
  const { createServiceLoop } = host('service-loop.js');
  const { createRestartGuard } = host('version-guard.js');
  const guardDir = tmp();
  const startGuard = createRestartGuard({ userData: guardDir, file: 'f.json', max: 5, windowMs: 1800000 });
  const loop = createServiceLoop({ manager: { getState: () => (holderGone ? 'running' : 'stopped'), engineIsUp: async () => holderGone, getHealth: async () => ({ version: '1.0.0' }),
    getBindReport: () => ({ setup_status: 'unpaired', bind: { restart_required: false } }),
    start: async () => { starts += 1; if (!holderGone) { const e = new Error('Port 8000 is already in use by another process, which is not a Carnivore server.'); e.code = 'PORT_HOLDER_NOT_CARNIVORE'; throw e; } } },
    running: '1.0.0', readDisk: () => '1.0.0', guard: createRestartGuard({ userData: tmp() }), decideRebind: () => 'none', stopEngine: async () => {},
    startGuard, exit: () => { exits += 1; }, log: (m) => lines.push(m), now: () => clock, sleep: async () => {}, healthWaitMs: 1000 });
  for (let i = 0; i < 40; i += 1) { await loop.tick(); clock += 15000; }
  assert.equal(exits, 0, 'the service must not exit 0 and stay down');
  assert.ok(starts >= 8 && starts <= 12, `start attempts: ${starts}`);
  assert.ok(lines.length <= 2, `lines: ${lines.length}`);
  assert.equal(startGuard.allow('1.0.0'), true, 'no failure was recorded');
  holderGone = true;
  clock += 60000;
  await loop.tick();
  assert.equal(exits, 0);
});

t('proof 4b: start() tags the non-Carnivore refusal with the code the service waits on', () => {
  const src = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
  assert.match(src, /refusal\.code = 'PORT_HOLDER_NOT_CARNIVORE'/);
});

async function stopGateRig({ owned = false, adoptedVersion = null, adoptedPid = null, holderPid = null, state = 'stopped', diskVersion = '1.0.0', health = null, rebind = 'none' }) {
  const lifecycle = require(path.join(macDir, 'engine', 'engine-lifecycle.js'));
  const { ownedStop } = host('owned-stop.js');
  const { createServiceLoop } = host('service-loop.js');
  const { installTermHandler } = host('teardown.js');
  const { createRestartGuard } = host('version-guard.js');
  const listener = net.createServer();
  await new Promise((res) => listener.listen(0, '127.0.0.1', res));
  const rig = { listener, shutdowns: 0, holderUp: true, exits: [], lines: [], disk: diskVersion, health, rebinds: 0 };
  const manager = { ownedProcess: owned, adoptedVersion, state, processPid: adoptedPid, findPortHolderPid: async () => holderPid, getState: () => manager.state, getPort: () => listener.address().port, engineIsUp: async () => rig.holderUp,
    stop: async () => { rig.signals = (rig.signals || 0) + 1; rig.holderUp = false; return { stopped: true }; },
    getHealth: async () => rig.health, getBindReport: () => ({}), restart: async () => ({ refused: true }), restartAdoptedEngine: async () => { rig.rebinds += 1; rig.shutdowns += 1; return { restarted: true }; }, start: async () => { const e = new Error('refused'); e.code = 'ADOPTION_REFUSED'; e.outcome = 'version-mismatch'; throw e; } };
  const api = { sendAuthed: async () => { rig.shutdowns += 1; rig.holderUp = false; return { reachable: true }; } };
  const stopEngine = ownedStop({ manager, stopEngine: () => lifecycle.stopEngine(manager, { getApi: () => api }) });
  rig.loop = createServiceLoop({ manager, running: '1.0.0', readDisk: () => rig.disk, guard: createRestartGuard({ userData: tmp() }), decideRebind: () => rebind, stopEngine,
    startGuard: createRestartGuard({ userData: tmp(), file: 'f.json', max: 5, windowMs: 1800000 }), exit: (c) => rig.exits.push(c), log: (m) => rig.lines.push(m), sleep: async () => {} });
  const proc = new EventEmitter();
  rig.term = installTermHandler({ proc, role: 'service', quit: () => {}, stopEngine, exit: (c) => rig.exits.push(c), log: (m) => rig.lines.push(m) });
  return rig;
}
const stopLines = (r) => r.lines.filter((l) => l.includes('not stopping') || l.includes('stop'));

t('P11 stop gate (a): waiting on a refused same-user holder, a bundle version change exits for the restart and never shuts the holder down; one log line', async () => {
  const r = await stopGateRig({});
  await r.loop.tick();
  r.disk = '1.1.0';
  assert.equal(await r.loop.tick(), 'exit-for-update');
  assert.equal(r.shutdowns, 0, 'no shutdown call may reach the holder');
  assert.equal(r.holderUp, true);
  assert.equal(r.lines.filter((l) => l.includes('leaving the port holder alone')).length, 1, r.lines.join(' | '));
  r.listener.close();
});

t('P11 stop gate (b): waiting on a refused same-user holder, the SIGTERM teardown exits 0 and never shuts the holder down; one log line', async () => {
  const r = await stopGateRig({});
  await r.loop.tick();
  await r.term();
  assert.deepEqual(r.exits, [0]);
  assert.equal(r.shutdowns, 0);
  assert.equal(r.holderUp, true);
  assert.equal(r.lines.filter((l) => l.includes('leaving the port holder alone')).length, 1, r.lines.join(' | '));
  r.listener.close();
});

t('P11 stop gate controls: an engine the service started is signalled on teardown and on a version restart; an adopted same-version engine goes through the route on teardown', async () => {
  const started = await stopGateRig({ owned: true, state: 'running' });
  await started.term();
  assert.equal(started.signals, 1);
  const restart = await stopGateRig({ owned: true, state: 'running' });
  restart.disk = '1.1.0';
  assert.equal(await restart.loop.tick(), 'exit-for-update');
  assert.equal(restart.signals, 1);
  const adopted = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running' });
  await adopted.term();
  assert.equal(adopted.shutdowns, 1);
  assert.equal(adopted.holderUp, false);
  for (const x of [started, restart, adopted]) x.listener.close();
});

t('P11 stop gate (c): an adopted engine replaced by an other-version holder is no longer ours; teardown, the version restart and the first-run rebind send it nothing, with a log line each', async () => {
  const teardown = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running', health: { version: '1.1.0' } });
  await teardown.term();
  assert.equal(teardown.shutdowns, 0, 'teardown must not shut the replacement down');
  assert.equal(teardown.holderUp, true);
  assert.equal(teardown.lines.filter((l) => l.includes('leaving the port holder alone')).length, 1, teardown.lines.join(' | '));
  const restart = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running', health: { version: '1.1.0' } });
  restart.disk = '1.2.0';
  assert.equal(await restart.loop.tick(), 'exit-for-update');
  assert.equal(restart.shutdowns, 0);
  assert.equal(restart.lines.filter((l) => l.includes('leaving the port holder alone')).length, 1, restart.lines.join(' | '));
  const rebind = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running', health: { version: '1.1.0' }, rebind: 'restart' });
  await rebind.loop.tick();
  assert.equal(rebind.rebinds, 0, 'the rebind must not restart a replaced engine');
  assert.equal(rebind.shutdowns, 0);
  assert.equal(rebind.holderUp, true);
  const same = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running', health: { version: '1.0.0' } });
  await same.term();
  assert.equal(same.shutdowns, 1);
  for (const x of [teardown, restart, rebind, same]) x.listener.close();
});

t('P11 stop gate (d): an adopted engine replaced by one that reports no version is no longer ours; teardown and the version restart send it nothing', async () => {
  const teardown = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running', health: {} });
  await teardown.term();
  assert.equal(teardown.shutdowns, 0, 'teardown must not shut a versionless replacement down');
  assert.equal(teardown.holderUp, true);
  const restart = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running', health: {} });
  restart.disk = '1.2.0';
  assert.equal(await restart.loop.tick(), 'exit-for-update');
  assert.equal(restart.shutdowns, 0);
  const slow = await stopGateRig({ adoptedVersion: '1.0.0', state: 'running', health: null });
  await slow.term();
  assert.equal(slow.shutdowns, 1);
  for (const x of [teardown, restart, slow]) x.listener.close();
});

t('P11 stop gate (e): a same-version engine with a different listener pid is no longer ours; an unreadable pid keeps the version-only answer', async () => {
  const swapped = await stopGateRig({ adoptedVersion: '1.0.0', adoptedPid: 4101, holderPid: 4202, state: 'running', health: { version: '1.0.0' } });
  await swapped.term();
  assert.equal(swapped.shutdowns, 0, 'teardown must not shut a same-version stranger down');
  assert.equal(swapped.holderUp, true);
  const same = await stopGateRig({ adoptedVersion: '1.0.0', adoptedPid: 4101, holderPid: 4101, state: 'running', health: { version: '1.0.0' } });
  await same.term();
  assert.equal(same.shutdowns, 1);
  const unreadable = await stopGateRig({ adoptedVersion: '1.0.0', adoptedPid: 4101, holderPid: null, state: 'running', health: { version: '1.0.0' } });
  await unreadable.term();
  assert.equal(unreadable.shutdowns, 1);
  for (const x of [swapped, same, unreadable]) x.listener.close();
});

t('P11 stop gate (f): the first-run rebind restarts the adopted engine, but not a same-version engine with a different listener pid', async () => {
  const swapped = await stopGateRig({ adoptedVersion: '1.0.0', adoptedPid: 4101, holderPid: 4202, state: 'running', health: { version: '1.0.0' }, rebind: 'restart' });
  await swapped.loop.tick();
  assert.equal(swapped.rebinds, 0, 'the rebind must not stop a same-version stranger');
  assert.equal(swapped.holderUp, true);
  const same = await stopGateRig({ adoptedVersion: '1.0.0', adoptedPid: 4101, holderPid: 4101, state: 'running', health: { version: '1.0.0' }, rebind: 'restart' });
  await same.loop.tick();
  assert.equal(same.rebinds, 1);
  for (const x of [swapped, same]) x.listener.close();
});

let failed = 0;
t('#2493 follow-up A: the tray login-off click writes launchAtLogin false at once and keeps carriedBy; the retire rule is untouched', () => {
  const { markLoginOff } = host('login-sync.js');
  const { trayLogin } = host('tray-login.js');
  const { readRecord, retireLaunchAgent } = require(path.join(macDir, 'engine', 'login-handoff.js'));
  const r = syncRig({ launchAtLogin: true });
  fs.writeFileSync(path.join(r.userData, 'login-migration.json'), `${JSON.stringify({ launchAtLogin: true, windowAtLogin: false, recordedAt: 'x', carriedBy: 'R2-06' })}\n`);
  let on = true;
  const service = { isEnabled: () => on, unregister: () => { on = false; return 'notRegistered'; }, register: () => { on = true; return 'enabled'; } };
  const facade = trayLogin({ strategy: 'launchd-agent', installer: r.installer, service, userData: r.userData });
  facade.toggle();
  const after = readRecord(r.userData);
  assert.equal(after.launchAtLogin, false);
  assert.equal(after.carriedBy, 'R2-06');
  assert.equal(markLoginOff(tmp(), () => {}), false, 'no record: nothing written, no throw');
  assert.equal(retireLaunchAgent({ userData: r.userData, installer: r.installer, ready: true, keepForBackground: false }).retired, true, 'carriedBy still gates the retire');
});

t('#2497: the settings page engine-off click and the detached tray row record launchAtLogin false at once', () => {
  const { setLogin } = require(path.join(macDir, 'login-items.js'));
  const { trayLogin } = host('tray-login.js');
  const { readRecord } = require(path.join(macDir, 'engine', 'login-handoff.js'));
  const seed = (r) => fs.writeFileSync(path.join(r.userData, 'login-migration.json'), `${JSON.stringify({ launchAtLogin: true, windowAtLogin: false, recordedAt: 'x' })}\n`);
  const mk = (r) => Object.assign(r.installer, { enable() { this.on = true; }, disable() { this.on = false; }, toggle() { this.on = !this.on; } });
  const a = syncRig({ launchAtLogin: true }); seed(a); mk(a);
  setLogin({ installer: a.installer, launchArgs: () => [], dir: a.userData, which: 'engine', enabled: false });
  assert.equal(readRecord(a.userData).launchAtLogin, false, 'detached settings click');
  const b = syncRig({ launchAtLogin: true }); seed(b); mk(b);
  const service = { on: true, isEnabled() { return this.on; }, unregister() { this.on = false; }, register() { this.on = true; } };
  setLogin({ installer: b.installer, service, launchArgs: () => [], dir: b.userData, which: 'engine', enabled: false });
  assert.equal(readRecord(b.userData).launchAtLogin, false, 'service settings click');
  const c = syncRig({ launchAtLogin: true }); seed(c); mk(c);
  trayLogin({ strategy: 'detached', installer: c.installer, service: null, userData: c.userData }).toggle([]);
  assert.equal(readRecord(c.userData).launchAtLogin, false, 'detached tray row');
});

t('#2493 follow-up B: the service logs ONE plain line naming the port and that the holder is not ours, not one per retry', async () => {
  let clock = 0; const lines = [];
  const { createServiceLoop } = host('service-loop.js');
  const { createRestartGuard } = host('version-guard.js');
  const loop = createServiceLoop({ manager: { getState: () => 'stopped', engineIsUp: async () => false, getHealth: async () => null, getPort: () => 8000,
    getBindReport: () => ({}), start: async () => { const e = new Error('refused'); e.code = 'ADOPTION_REFUSED'; e.outcome = 'version-mismatch'; e.pid = 111; e.port = 8000; throw e; } },
    running: '1.0.0', readDisk: () => '1.0.0', guard: createRestartGuard({ userData: tmp() }), decideRebind: () => 'none', stopEngine: async () => {},
    startGuard: createRestartGuard({ userData: tmp(), file: 'f.json', max: 5, windowMs: 1800000 }), exit: () => {}, log: (m) => lines.push(m), now: () => clock, sleep: async () => {}, healthWaitMs: 1000 });
  for (let i = 0; i < 20; i += 1) { await loop.tick(); clock += 15000; }
  const held = lines.filter((l) => /port 8000 is held by a process that is not ours/.test(l));
  assert.equal(held.length, 1, `lines: ${lines.join(' | ')}`);
});

for (const [name, fn] of queue) {
  try {
    await fn();
    console.log(`ok   ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`FAIL ${name}\n${err && err.stack}`);
  }
}
console.log(failed ? `${failed} of ${queue.length} failed` : `all ${queue.length} passed`);
process.exit(failed ? 1 : 0);
