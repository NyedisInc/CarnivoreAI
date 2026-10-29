import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const fixtureRows = JSON.parse(
  fs.readFileSync(path.join(import.meta.dirname, '..', 'fixtures', 'otpauth_uri_cases.json'), 'utf8')
);

function fresh() {
  const p = require.resolve(path.join(macDir, 'rebind-after-pair.js'));
  delete require.cache[p];
  return require(p);
}
const flush = () => new Promise((r) => setImmediate(r));
async function advance(ms) {
  for (let t = 0; t < ms; t += 2000) {
    mock.timers.tick(2000);
    await flush();
  }
}
const COMPLETE = { setup_status: 'complete', bind: { restart_required: true } };
const verdict = (over = {}) => ({
  status: 'incomplete',
  checks: [
    { key: 'config_file', passed: true }, { key: 'totp_secret', passed: true },
    { key: 'jwt_secret', passed: true }, { key: 'totp_paired', passed: false },
  ],
  ...over,
});

test('decide: the restart trigger needs complete AND restart_required', () => {
  const { decide } = fresh();
  const now = 1_000_000;
  assert.equal(decide(COMPLETE, { attempted: false, attemptAt: null, now }), 'restart');
  assert.equal(decide(COMPLETE, { attempted: true, attemptAt: now - 59000, now }), 'wait');
  assert.equal(decide(COMPLETE, { attempted: true, attemptAt: now - 60000, now }), 'stuck');
  assert.equal(decide({ setup_status: 'incomplete', bind: { restart_required: true } },
    { attempted: false, attemptAt: null, now }), 'wait');
  assert.equal(decide({ setup_status: 'complete', bind: { restart_required: false } }, { attempted: false, now }), 'stop');
  assert.equal(decide({ setup_status: 'complete', bind: { restart_required: null } }, { attempted: false, now }), 'stop');
  assert.equal(decide({ setup_status: null, bind: null }, { attempted: false, now }), 'wait');
  assert.equal(decide({ setup_status: 'undetermined', bind: {} }, { attempted: false, now }), 'wait');
});

test('shouldAutoOpen: only a pairing gap on a server this app owns', () => {
  const { shouldAutoOpen } = fresh();
  assert.equal(shouldAutoOpen(verdict(), true, 42, 42), true);
  const noConfig = verdict();
  noConfig.checks[0].passed = false;
  assert.equal(shouldAutoOpen(noConfig, true, 42, 42), false);
  const unknownSecret = verdict();
  unknownSecret.checks[1].passed = null;
  assert.equal(shouldAutoOpen(unknownSecret, true, 42, 42), false);
  assert.equal(shouldAutoOpen(verdict(), false, 42, 42), false);
  assert.equal(shouldAutoOpen(verdict(), true, 43, 42), false);
  assert.equal(shouldAutoOpen(verdict(), true, null, 42), false);
  assert.equal(shouldAutoOpen(verdict({ status: 'undetermined' }), true, 42, 42), false);
  assert.equal(shouldAutoOpen(verdict({ status: 'complete' }), true, 42, 42), false);
});

test('maybeAutoOpenFirstRun: latch, unhealthy server, bad port, port passed through', async () => {
  const mod = fresh();
  let opens = 0;
  let seenPort = null;
  const sm = {
    getSetupVerdict: () => verdict(), ownedProcess: true, processPid: 7,
    getPort: () => 8123,
    findPortHolderPid: async (port) => { seenPort = port; return 7; },
  };
  const appWindow = { open: () => { opens++; } };
  assert.equal(await mod.maybeAutoOpenFirstRun({ serverManager: sm, appWindow, waitForServerHealth: async () => false }), false);
  assert.equal(opens, 0);
  const badPort = { ...sm, getPort: () => { throw new Error('bad PORT'); } };
  assert.equal(await mod.maybeAutoOpenFirstRun({ serverManager: badPort, appWindow, waitForServerHealth: async () => true }), false);
  assert.equal(opens, 0);
  const ok = () => mod.maybeAutoOpenFirstRun({ serverManager: sm, appWindow, waitForServerHealth: async () => true });
  assert.equal(await ok(), true);
  assert.equal(seenPort, 8123);
  assert.equal(await ok(), false);
  assert.equal(opens, 1);
});

function harness(reports, { restart, response = 0 } = {}) {
  let i = 0;
  const calls = { getHealth: 0, restart: [], offer: 0, fail: 0, message: 0, error: 0 };
  const sm = {
    getHealth: async () => { calls.getHealth++; },
    getBindReport: () => reports(i++),
    restart: async (opts) => { calls.restart.push(opts); return restart ? restart() : { restarted: true }; },
  };
  const deps = {
    serverManager: sm,
    offerTakeOwnership: async () => { calls.offer++; },
    reportStartFailure: async () => { calls.fail++; },
    dialog: {
      showMessageBox: async () => { calls.message++; return { response }; },
      showErrorBox: () => { calls.error++; },
    },
  };
  return { deps, calls };
}
const WAIT = { setup_status: 'incomplete', bind: { restart_required: true } };
const STOP = { setup_status: 'complete', bind: { restart_required: false } };

test('watch', async (t) => {
  const run = async (name, fn) => t.test(name, async () => {
    mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
    try { await fn(fresh()); } finally { mock.timers.reset(); }
  });

  await run('(a) owned: restart exactly once across 10 more ticks', async (mod) => {
    const { deps, calls } = harness(() => COMPLETE);
    mod.startWatch(deps);
    await advance(2000);
    assert.equal(calls.restart.length, 1);
    assert.equal(calls.restart[0], undefined, 'never takeOwnership');
    await advance(20000);
    assert.equal(calls.restart.length, 1);
  });

  await run('(b) adopted: consent dialog once, never takeOwnership', async (mod) => {
    const { deps, calls } = harness(() => COMPLETE, { restart: () => ({ refused: true }) });
    mod.startWatch(deps);
    await advance(20000);
    assert.equal(calls.offer, 1);
    assert.equal(calls.restart.length, 1);
    assert.ok(calls.restart.every((o) => !o || o.takeOwnership !== true));
  });

  await run('(c) restart throws: one failure report, no second attempt', async (mod) => {
    const { deps, calls } = harness(() => COMPLETE, { restart: () => { throw new Error('boom'); } });
    mod.startWatch(deps);
    await advance(20000);
    assert.equal(calls.fail, 1);
    assert.equal(calls.restart.length, 1);
    mod.startWatch(deps);
    await advance(20000);
    assert.equal(calls.restart.length, 1);
  });

  await run('(d) stale incomplete twice then complete: restart on the next tick', async (mod) => {
    const { deps, calls } = harness((i) => (i < 2 ? WAIT : COMPLETE));
    mod.startWatch(deps);
    await advance(4000);
    assert.equal(calls.restart.length, 0);
    await advance(2000);
    assert.equal(calls.restart.length, 1);
  });

  await run('(e) paired at boot: never restarts and the watch stops', async (mod) => {
    const { deps, calls } = harness(() => STOP);
    mod.startWatch(deps);
    await advance(2000);
    const seen = calls.getHealth;
    await advance(30000);
    assert.equal(calls.restart.length, 0);
    assert.equal(calls.getHealth, seen);
  });

  await run('(f) restart loop: one restart, one stuck dialog, then silence', async (mod) => {
    const { deps, calls } = harness(() => COMPLETE);
    mod.startWatch(deps);
    await advance(5 * 60 * 1000);
    assert.equal(calls.restart.length, 1);
    assert.equal(calls.message, 1);
    const seen = calls.getHealth;
    await advance(60000);
    assert.equal(calls.getHealth, seen);
  });

  await run('(f2) stale cache after the restart: no second restart, no dialog', async (mod) => {
    let restarted = -1;
    const { deps, calls } = harness((i) => (restarted >= 0 && i >= restarted + 3 ? STOP : COMPLETE), {
      restart: () => { restarted = 1; return { restarted: true }; },
    });
    mod.startWatch(deps);
    await advance(30000);
    assert.equal(calls.restart.length, 1);
    assert.equal(calls.message, 0);
  });

  await run('(f3) stuck dialog answered Restart Server: one more restart, no re-arm', async (mod) => {
    const { deps, calls } = harness(() => COMPLETE, { response: 1 });
    mod.startWatch(deps);
    await advance(90000);
    assert.equal(calls.restart.length, 2);
    const seen = calls.getHealth;
    await advance(10 * 60 * 1000);
    assert.equal(calls.restart.length, 2);
    assert.equal(calls.getHealth, seen);
  });

  await run('(g) bounded: 2 s ticks, 10 minute deadline, one timer, stop is final', async (mod) => {
    const { deps, calls } = harness(() => WAIT);
    mod.startWatch(deps);
    await advance(10000);
    assert.equal(calls.getHealth, 5);
    await advance(2 * 60 * 1000 - 10000 + 3 * 60 * 1000);
    mod.startWatch(deps);
    const before = calls.getHealth;
    await advance(10000);
    assert.equal(calls.getHealth - before, 5);
    await advance(11 * 60 * 1000);
    const after = calls.getHealth;
    await advance(60000);
    assert.equal(calls.getHealth, after, 'no getHealth after the deadline');
    assert.ok(after - before >= 295 && after - before <= 305, 'ticked until minute 15: ' + (after - before));

    const second = harness(() => STOP);
    const mod2 = fresh();
    mod2.startWatch(second.deps);
    await advance(4000);
    const seen = second.calls.getHealth;
    mod2.startWatch(second.deps);
    await advance(10000);
    assert.equal(second.calls.getHealth, seen, 'a start after stop schedules nothing');
  });
});

test('a pairing that still needs the rebind restart reloads the window after the restart, never into it (#2471)', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  try {
    const mod = fresh();
    const unpaired = { setup_status: 'incomplete', joined: false, bind: { restart_required: true }, rebind_requested: false };
    const pairedOnLoopback = { ...unpaired, setup_status: 'complete' };
    const rebound = { ...pairedOnLoopback, bind: { restart_required: false } };
    let report = unpaired;
    const log = [];
    const deps = {
      serverManager: {
        getHealth: async () => {},
        getBindReport: () => report,
        restart: async () => { log.push('restart'); report = rebound; return { restarted: true }; },
      },
      appWindow: { isOpen: () => true, open: () => log.push('open'), reload: () => log.push('reload'), rehome: () => false },
      offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
    };
    mod.observeHealth(deps);
    report = pairedOnLoopback;
    mod.observeHealth(deps);
    await advance(6000);
    assert.deepEqual(log, ['restart', 'reload']);
  } finally { mock.timers.reset(); }
});

test('a pairing seen while the watch is already restarting the engine still holds the reload until the restart ends (#2471)', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  try {
    const mod = fresh();
    const unpaired = { setup_status: 'incomplete', joined: false, bind: { restart_required: true }, rebind_requested: true };
    const pairedOnLoopback = { ...unpaired, setup_status: 'complete' };
    let report = unpaired;
    const log = [];
    let deps;
    deps = {
      serverManager: {
        getHealth: async () => {},
        getBindReport: () => report,
        restart: async () => {
          log.push('restart-start');
          mod.observeHealth(deps);
          report = { ...pairedOnLoopback, bind: { restart_required: false } };
          log.push('restart-end');
          return { restarted: true };
        },
      },
      appWindow: { isOpen: () => true, open: () => log.push('open'), reload: () => log.push('reload'), rehome: () => false },
      offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
    };
    mod.observeHealth(deps);
    report = pairedOnLoopback;
    await advance(2000);
    assert.deepEqual(log, ['restart-start', 'restart-end', 'reload']);
  } finally { mock.timers.reset(); }
});

test('the held window reload waits for the restarted engine to answer health, never fires on a spawned but not listening engine', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  try {
    const mod = fresh();
    const unpaired = { setup_status: 'incomplete', joined: false, bind: { restart_required: true }, rebind_requested: false };
    const pairedOnLoopback = { ...unpaired, setup_status: 'complete' };
    let report = unpaired;
    const log = [];
    let release;
    const deps = {
      serverManager: {
        getHealth: async () => {},
        getBindReport: () => report,
        restart: async () => { log.push('restart'); report = { ...pairedOnLoopback, bind: { restart_required: false } }; return { restarted: true }; },
      },
      waitForServerHealth: () => new Promise((r) => { release = () => { log.push('healthy'); r(true); }; }),
      appWindow: { isOpen: () => true, open: () => log.push('open'), reload: () => log.push('reload'), rehome: () => false },
      offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
    };
    mod.observeHealth(deps);
    report = pairedOnLoopback;
    mod.observeHealth(deps);
    await advance(4000);
    assert.deepEqual(log, ['restart'], 'no reload while the new engine is not answering yet');
    release();
    await flush();
    await flush();
    assert.deepEqual(log, ['restart', 'healthy', 'reload']);
  } finally { mock.timers.reset(); }
});

test('the held reload after the first-launch restart goes through the window guard, so a still-blocked guard cannot cancel it (#2503)', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  try {
    const mod = fresh();
    const unpaired = { setup_status: 'incomplete', joined: false, bind: { restart_required: true }, rebind_requested: false };
    const pairedOnLoopback = { ...unpaired, setup_status: 'complete' };
    let report = unpaired;
    let guardBlocked = true;
    const log = [];
    const deps = {
      serverManager: {
        getHealth: async () => {},
        getBindReport: () => report,
        restart: async () => { report = { ...pairedOnLoopback, bind: { restart_required: false } }; return { restarted: true }; },
      },
      waitForServerHealth: async () => true,
      whenGuardClear: (load) => { if (guardBlocked) { log.push('held'); guardBlocked = false; log.push('cleared'); } load(); },
      appWindow: { isOpen: () => true, open: () => {}, reload: () => log.push(guardBlocked ? 'reload-cancelled' : 'reload'), rehome: () => false },
      offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
    };
    mod.observeHealth(deps);
    report = pairedOnLoopback;
    mod.observeHealth(deps);
    await advance(4000);
    assert.deepEqual(log, ['held', 'cleared', 'reload']);
  } finally { mock.timers.reset(); }
});

test('first launch, fresh unpaired install: the first-run auto-open waits on the same settle, so the restart finishes before the window (#2522)', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  try {
    const run = async (blockAfterRestart) => {
      const mod = fresh();
      const log = [];
      let report = { setup_status: 'complete', joined: false, bind: { restart_required: true }, rebind_requested: false };
      const serverManager = {
        getHealth: async () => {}, getBindReport: () => report, getSetupVerdict: () => verdict(),
        ownedProcess: true, processPid: 7, getPort: () => 8000, findPortHolderPid: async () => 7, startBlockedReason: null,
        restart: async () => {
          log.push('restart-begin'); report = { ...report, bind: { restart_required: false } };
          if (blockAfterRestart) serverManager.startBlockedReason = 'holder-foreign';
          log.push('restart-spawned'); return { restarted: true };
        },
      };
      const deps = {
        serverManager, offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
        waitForServerHealth: async () => { log.push('health'); return true; }, whenGuardClear: (load) => load(),
        appWindow: { isOpen: () => false, open: () => log.push('window-open'), reload: () => log.push('reload'), rehome: () => false },
      };
      const opened = mod.maybeAutoOpenFirstRun({
        serverManager, appWindow: deps.appWindow, waitForServerHealth: deps.waitForServerHealth,
        settle: () => mod.settleBeforeFirstWindow(deps),
      });
      mod.startWatch(deps);
      const result = await opened;
      await advance(4000);
      return { log, result };
    };
    const ok = await run(false);
    assert.equal(ok.result, true);
    assert.deepEqual(ok.log.slice(0, 4), ['health', 'restart-begin', 'restart-spawned', 'health'], 'the restart runs before the window');
    assert.deepEqual(ok.log.filter((l) => l === 'restart-begin' || l === 'window-open'), ['restart-begin', 'window-open']);
    const blocked = await run(true);
    assert.equal(blocked.result, false);
    assert.equal(blocked.log.includes('window-open'), false);
  } finally { mock.timers.reset(); }
});

test('first launch: the window opens only after the app\'s own rebind restart finished, and our own stop is never a refused holder (#2516)', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  try {
    const mod = fresh();
    const log = [];
    let report = { setup_status: 'complete', joined: false, bind: { restart_required: true }, rebind_requested: false };
    const serverManager = {
      getHealth: async () => {},
      getBindReport: () => report,
      restart: async () => { log.push('restart-begin'); report = { ...report, bind: { restart_required: false } }; log.push('restart-spawned'); return { restarted: true }; },
    };
    const deps = {
      serverManager, offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
      waitForServerHealth: async () => { log.push('health'); return true; },
      whenGuardClear: (load) => load(),
      appWindow: { isOpen: () => false, open: () => log.push('window-open'), reload: () => log.push('reload'), rehome: () => false },
    };
    mod.startWatch(deps);
    const waited = await mod.settleBeforeFirstWindow(deps);
    deps.appWindow.open();
    await advance(4000);
    assert.equal(waited, true);
    assert.deepEqual(log, ['restart-begin', 'restart-spawned', 'health', 'window-open'], 'one restart, finished before the window, none after');

    const { wireWindowGuard } = require(path.join(macDir, 'window-guard-wire.js'));
    const manager = { stopRequested: true, getPort: () => 8000, getHealth: async () => ({ uptime: 5 }), startBlockedReason: null };
    const g = wireWindowGuard({ getManager: () => manager, refreshTray: () => {}, reload: () => {} });
    g.noteDown();
    await g.onHealth(true, { uptime: 5 });
    await g.onStopped();
    assert.equal(manager.startBlockedReason, null, 'our own stop must not raise a holder refusal');
  } finally { mock.timers.reset(); }
});

test('first launch: the settle waits for a report that is not final at the first healthy answer, and restarts before the window opens (#2517)', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  try {
    const mod = fresh();
    const log = [];
    let report = { setup_status: null, joined: false, bind: { restart_required: true }, rebind_requested: false };
    const flipAt = Date.now() + 1500;
    const serverManager = {
      getHealth: async () => { if (Date.now() >= flipAt) report = { ...report, setup_status: 'complete' }; },
      getBindReport: () => report,
      restart: async () => { log.push('restart'); report = { ...report, bind: { restart_required: false } }; return { restarted: true }; },
    };
    const deps = {
      serverManager, offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
      waitForServerHealth: async () => true,
      whenGuardClear: (load) => load(),
      appWindow: { isOpen: () => false, open: () => log.push('window-open'), reload: () => {}, rehome: () => false },
    };
    let waited = null;
    const settled = mod.settleBeforeFirstWindow(deps).then((w) => { waited = w; });
    for (let t = 0; t < 4000 && waited === null; t += 250) { mock.timers.tick(250); await flush(); await flush(); }
    await settled;
    deps.appWindow.open();
    assert.equal(waited, true);
    assert.deepEqual(log, ['restart', 'window-open'], 'the restart ran before the window opened');

    const quiet = fresh();
    const done = await quiet.settleBeforeFirstWindow({
      ...deps, serverManager: { getHealth: async () => {}, getBindReport: () => ({ setup_status: 'complete', joined: false, bind: { restart_required: false } }), restart: async () => { throw new Error('no restart'); } },
    });
    assert.equal(done, false);
  } finally { mock.timers.reset(); }
});

test('a baseline taken while no window was open never reloads the window the first launch then opens (#2523)', () => {
  const mod = fresh();
  let open = false;
  let report = { setup_status: 'incomplete', joined: false, bind: { restart_required: true }, rebind_requested: false };
  const log = [];
  const deps = {
    serverManager: { getHealth: async () => {}, getBindReport: () => report },
    appWindow: { isOpen: () => open, open: () => log.push('open'), reload: () => log.push('reload'), rehome: () => false },
    offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
  };
  mod.observeHealth(deps);
  open = true;
  report = { ...report, setup_status: 'complete', bind: { restart_required: false } };
  mod.observeHealth(deps);
  assert.deepEqual(log, [], 'no reload');
  const again = fresh();
  report = { setup_status: 'incomplete', joined: false, bind: { restart_required: false }, rebind_requested: false };
  again.observeHealth(deps);
  report = { ...report, setup_status: 'complete' };
  again.observeHealth(deps);
  assert.deepEqual(log, ['reload']);
});

test('ServerManager.getBindReport copies, never aliases, and is found by name', () => {
  const src = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
  const start = src.indexOf('\n  getBindReport() {');
  assert.notEqual(start, -1, 'getBindReport not found');
  const end = src.indexOf('\n  }\n', start + 1);
  const obj = new Function('return {' + src.slice(start, end + 5) + '}')();
  assert.deepEqual(obj.getBindReport.call({ reportedSetupStatus: null, reportedBind: null }),
    { setup_status: null, bind: null, joined: null, rebind_requested: false, door_file: null });
  const fake = { reportedSetupStatus: 'complete', reportedBind: { restart_required: true } };
  const report = obj.getBindReport.call(fake);
  assert.deepEqual(report, { setup_status: 'complete', bind: { restart_required: true }, joined: null, rebind_requested: false, door_file: null });
  report.bind.restart_required = false;
  assert.equal(fake.reportedBind.restart_required, true);
});

test('otpauth-uri: every row of the shared fixture', () => {
  const { sanitizeAccount, buildOtpauthUri } = require(path.join(macDir, 'otpauth-uri.js'));
  assert.ok(fixtureRows.length >= 12);
  for (const row of fixtureRows) {
    assert.equal(sanitizeAccount(row.computer_name), row.account, JSON.stringify(row.computer_name));
    assert.equal(buildOtpauthUri(row.secret, row.computer_name), row.uri, JSON.stringify(row.computer_name));
  }
});

test('qr-window: carnivore look from theme.json, safe values only, literal QR plate', async () => {
  const qr = require(path.join(macDir, 'qr-window.js'));
  const row = fixtureRows[0];
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'qrwin-'));
  const serverDir = path.join(tmp, 'server');
  fs.mkdirSync(serverDir);
  fs.writeFileSync(path.join(serverDir, '.env'), `TOTP_SECRET=${row.secret}\n`);
  const themeDir = path.join(tmp, 'root', 'client', 'css', 'themes', 'carnivore');
  const root = path.join(tmp, 'root');

  async function show(projectRoot) {
    const made = [];
    class FakeWindow {
      constructor(opts) { this.opts = opts; this.url = null; made.push(this); }
      loadURL(u) { this.url = u; }
      once() {}
      setMenu() {}
    }
    let uri = null;
    const QRCode = { toString: async (text) => { uri = text; return '<svg id="qr"></svg>'; } };
    const ok = await qr.showQrPairingWindow({
      serverDir, projectRoot, BrowserWindow: FakeWindow, QRCode, computerName: row.computer_name,
    });
    assert.equal(ok, true);
    const html = decodeURIComponent(made[0].url.slice('data:text/html;charset=utf-8,'.length));
    return { html, opts: made[0].opts, uri };
  }

  let r = await show(root);
  assert.equal(r.uri, row.uri);
  assert.ok(!/--color-/.test(r.html.replace(/var\(--color-[a-z-]+\)/g, '')), 'no custom property emitted');
  assert.ok(/#ffffff/.test(r.html));
  assert.ok(!/Cloude/i.test(r.html) && !/Cloude/i.test(r.opts.title));
  assert.equal(r.opts.backgroundColor, undefined);

  fs.mkdirSync(themeDir, { recursive: true });
  fs.writeFileSync(path.join(themeDir, 'theme.json'), JSON.stringify({
    cssVars: { '--color-bg': '#02161e', '--color-fg': '#eaebed', '--color-accent': 'red;}body{display:none' },
  }));
  r = await show(root);
  assert.ok(r.html.includes('--color-bg:#02161e;'));
  assert.equal(r.opts.backgroundColor, '#02161e');
  assert.ok(!r.html.includes('--color-accent'), 'a value containing ;} is left out');
  assert.ok(!r.html.includes('display:none'));
  fs.rmSync(tmp, { recursive: true, force: true });
});
