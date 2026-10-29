
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const macDir = path.join(repoRoot, 'macOS');

const trayStatus = require(path.join(macDir, 'tray-status.js'));

let passed = 0;
let failed = 0;

function test(name, body) {
  try {
    body();
    passed += 1;
    console.log(`  ok   ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`  FAIL ${name}`);
    console.log(`       ${err.message}`);
  }
}

function runningInput(overrides) {
  return Object.assign(
    {
      serverState: 'running',
      sessions: [],
      sessionsReachable: true,
      updateState: 'current',
      setupStatus: 'complete',
    },
    overrides || {}
  );
}

console.log('setup signal');


test('an unfinished setup raises the SAME attention state the icon uses', () => {
  const derived = trayStatus.deriveTrayState(runningInput({ setupStatus: 'incomplete' }));
  assert.equal(derived.state, 'attention');
  assert.match(derived.reason, /setup is not finished/);
});

test('the attention state is one of the states the icon table already covers', () => {
  assert.ok(trayStatus.TRAY_STATES.includes('attention'));
});

test('an undetermined setup is attention, and says it could not be determined', () => {
  const derived = trayStatus.deriveTrayState(
    runningInput({ setupStatus: 'undetermined' })
  );
  assert.equal(derived.state, 'attention');
  assert.match(derived.reason, /could not be determined/);
});

test('a complete setup does not raise attention on its own', () => {
  assert.equal(trayStatus.deriveTrayState(runningInput()).state, 'ok');
});

test('setup outranks a session needing attention', () => {
  const derived = trayStatus.deriveTrayState(
    runningInput({
      setupStatus: 'incomplete',
      sessions: [{ activity_status: 'question' }],
    })
  );
  assert.equal(derived.state, 'attention');
  assert.match(derived.reason, /setup/);
});

test('setup does not override a stopped or crashed server', () => {
  const stopped = trayStatus.deriveTrayState({
    serverState: 'stopped',
    setupStatus: 'incomplete',
  });
  assert.equal(stopped.state, 'stopped');

  const crashed = trayStatus.deriveTrayState({
    serverState: 'stopped',
    lastExitUnexpected: true,
    setupStatus: 'incomplete',
  });
  assert.equal(crashed.state, 'crashed');
});


test('an unpolled setup status is NOT treated as complete', () => {
  const derived = trayStatus.deriveTrayState(runningInput({ setupStatus: null }));
  const signals = trayStatus.describeSignals(runningInput({ setupStatus: null }));
  assert.notEqual(signals.setup, 'complete');
  assert.match(signals.setup, /cannot determine/);
  assert.equal(derived.state, 'ok');
});

test('every setup verdict has its own distinct phrase', () => {
  const phrases = ['complete', 'incomplete', 'undetermined', null].map(
    (status) => trayStatus.describeSignals(runningInput({ setupStatus: status })).setup
  );
  assert.equal(new Set(phrases).size, 4, `phrases collapsed: ${phrases}`);
});

test('not-polled and undetermined are distinguishable, not both "unknown"', () => {
  const notPolled = trayStatus.describeSignals(runningInput({ setupStatus: null })).setup;
  const undetermined = trayStatus.describeSignals(
    runningInput({ setupStatus: 'undetermined' })
  ).setup;
  assert.notEqual(notPolled, undetermined);
});

test('the tooltip names the setup signal', () => {
  const tooltip = trayStatus.buildTooltip(runningInput({ setupStatus: 'incomplete' }));
  assert.match(tooltip, /Setup: not finished/);
});


import fs from 'node:fs';

const mainSrc = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
const serverModelSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'model', 'server.js'), 'utf8');
const snapshotSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'snapshot.js'), 'utf8');
const appActionsSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'actions', 'app.js'), 'utf8');
const managerSrc = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');

console.log('menu-bar wiring (source-level)');

test('the old config dialog is gone', () => {
  assert.ok(
    !/Check Config for New Defaults/.test(mainSrc + appActionsSrc + serverModelSrc),
    'the dialog menu item is still registered'
  );
});

test('the wizard is opened through shell.openExternal, like Open in Browser', () => {
  assert.match(appActionsSrc, /shell\.openExternal\(`\$\{base\}\/setup`\)/);
});

test('the setup row reads the snapshot verdict, never its own check', () => {
  const fn = serverModelSrc.slice(serverModelSrc.indexOf('function setupLabel('), serverModelSrc.indexOf('function setupHint('));
  assert.match(fn, /snap\.setup === 'incomplete'/);
  assert.ok(!/getSetupStatus|serverManager/.test(fn), 'the model must not read the server manager itself');
});

test('the tray input carries the setup status through to the tooltip', () => {
  assert.match(snapshotSrc, /setup:\s*sm\.getSetupVerdict\(\)\.status/);
  assert.match(snapshotSrc, /setupStatus:\s*snap\.setup/);
});

test('the icon and the setup ROW read the same verdict, never two', () => {
  for (const [name, src] of [['main.js', mainSrc], ['snapshot.js', snapshotSrc], ['actions/app.js', appActionsSrc]]) {
    assert.ok(!/\.getSetupStatus\(\)/.test(src.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')),
      `${name} still reads the raw server status instead of the verdict`);
  }
});

test('the published URL prefers the MEASURED bind over the configured one', () => {
  const { resolvePublishedUrl } = require(path.join(macDir, 'published-url.js'));
  assert.equal(
    resolvePublishedUrl({
      port: 8000,
      configuredHost: '0.0.0.0',
      measuredHost: '127.0.0.1',
      lanIp: '192.0.2.12',
    }),
    'http://127.0.0.1:8000',
    'the configured host beat the measured one, so the menu would print an ' +
    'aspiration rather than where the server actually is'
  );
  assert.match(managerSrc, /resolvePublishedUrl\(\{/);
});

test('the effective bind never falls back to the configured value', () => {
  const marker = '\n  getEffectiveBindHost() {';
  const start = managerSrc.indexOf(marker);
  assert.notEqual(start, -1, 'getEffectiveBindHost is not defined as a method');
  const fn = managerSrc.slice(start, start + 300);
  assert.ok(
    !/getBindHost\(\)/.test(fn),
    'getEffectiveBindHost falls back to configuration, which turns an ' +
      'aspiration into a reported measurement'
  );
});

test('the health probe also tries loopback, so the lockdown cannot look dead', () => {
  assert.match(managerSrc, /probeHostCandidates\(\)/);
  const fn = managerSrc.slice(
    managerSrc.indexOf('probeHostCandidates()'),
    managerSrc.indexOf('probeHostCandidates()') + 700
  );
  assert.match(fn, /127\.0\.0\.1/);
});

test('a failed exposure read clears the cached bind rather than keeping it', () => {
  const start = managerSrc.indexOf('async getHealth()');
  const end = managerSrc.indexOf('\n  getEffectiveBindHost() {');
  assert.ok(start !== -1 && end > start, 'could not locate getHealth');
  const fn = managerSrc.slice(start, end);
  assert.match(fn, /this\.reportedBind = null;/);
  assert.match(fn, /this\.reportedSetupStatus = null;/);
});


const setupJs = fs.readFileSync(path.join(repoRoot, 'client', 'setup.js'), 'utf8');
const apiJs = fs.readFileSync(path.join(repoRoot, 'client', 'js', 'api.js'), 'utf8');

console.log('wizard client');

test('the wizard reads the SAME token key the main web client writes', () => {
  const mine = setupJs.match(/const TOKEN_KEY = '([^']+)'/);
  assert.ok(mine, 'the wizard does not declare a TOKEN_KEY');
  const theirs = apiJs.match(/localStorage\.getItem\('([^']+)'\)/);
  assert.ok(theirs, 'could not find the main client token key in api.js');
  assert.equal(mine[1], theirs[1], `wizard uses ${mine[1]}, app uses ${theirs[1]}`);
});

test('the wizard posts to the auth endpoint that actually exists', () => {
  assert.ok(apiJs.includes('/auth/verify'));
  assert.match(setupJs, /fetch\('\/api\/v1\/auth\/verify'/);
});



import vm from 'node:vm';

function loadWizard(fetchImpl) {
  const els = new Map();
  const el = (id) => {
    if (!els.has(id)) els.set(id, { id, innerHTML: '', textContent: '', addEventListener() {} });
    return els.get(id);
  };
  const fetchCalls = [];
  const document = {
    getElementById: el,
    querySelectorAll: () => [],
    addEventListener() {},
    createElement() {
      let text = '';
      return {
        set textContent(v) { text = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
        get innerHTML() { return text; },
      };
    },
  };
  const ctx = vm.createContext({
    document,
    location: { assign() {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: (url, opts) => { fetchCalls.push(url); return fetchImpl(url, opts); },
    console,
  });
  vm.runInContext(setupJs, ctx);
  return { ctx, el, fetchCalls };
}

async function atest(name, body) {
  try {
    await body();
    passed += 1;
    console.log(`  ok   ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`  FAIL ${name}`);
    console.log(`       ${err.message}`);
  }
}

const localOnly403 = () => Promise.resolve({
  status: 403, ok: false, json: () => Promise.resolve({ detail: { reason: 'setup_local_only' } }),
});

console.log('wizard gate behaviour');

test('W4: first-run mode ends in the pair card, with no finish button or route', () => {
  const { ctx, el } = loadWizard(() => Promise.reject(new Error('no network in W4')));
  ctx.render({
    mode: 'first_run', setup: { checks: [] }, plan: { items: [] },
    exposure: { effective_host: '127.0.0.1', configured_host: '0.0.0.0', locked_down: true },
  });
  const html = el('wizard-body').innerHTML;
  assert.ok(html.includes('id="finish-pair"'));
  assert.ok(!html.includes('finish-btn'));
  assert.ok(!html.includes('/setup/finish'));
});

await atest('W5: a 403 setup_local_only on load shows the banner once, no retry', async () => {
  const { ctx, el, fetchCalls } = loadWizard(localOnly403);
  await ctx.load();
  assert.ok(el('wizard-body').innerHTML.includes('id="state-local-only"'));
  assert.equal(el('wizard-title').textContent, 'Finish setup on the computer');
  assert.equal(fetchCalls.length, 1);
});

await atest('W6: a 403 setup_local_only on apply prints the local-only line, never [object Object]', async () => {
  const { ctx, el } = loadWizard(localOnly403);
  await ctx.applyDecisions();
  const text = el('apply-status').textContent;
  assert.equal(text, 'Failed: setup can only be finished on the computer Carnivore runs on.');
  assert.ok(!text.includes('[object Object]'));
});

console.log('');
console.log(`setup signal: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
