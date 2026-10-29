import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Module from 'node:module';
import { spawnSync, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const macDir = path.join(root, 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));
const { spawnDetachedEngine } = require(path.join(macDir, 'engine', 'detached-spawn.js'));
const { stopEngineViaRoute, SHUTDOWN_ROUTE } = require(path.join(macDir, 'engine', 'engine-stop.js'));
const { decideAdoption } = require(path.join(macDir, 'adoption-decision.js'));
const { decideLifecycleAction } = require(path.join(macDir, 'ownership-policy.js'));
const { createQuitHandler } = require(path.join(macDir, 'quit-sequence.js'));
const policy = require(path.join(macDir, 'app-lifecycle-policy.js'));
const { TrayApiClient } = require(path.join(macDir, 'tray-api.js'));

const queue = [];
function t(name, fn) { queue.push([name, fn]); }
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function alive(pid) { try { process.kill(pid, 0); return true; } catch (err) { return err.code === 'EPERM'; } }
async function until(check, ms = 4000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await check()) return true; await sleep(40); }
  return Boolean(await check());
}
const size = (file) => fs.statSync(file).size;

function scene() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'detached-engine-'));
  const logs = path.join(dir, 'logs');
  fs.mkdirSync(logs, { mode: 0o755 });
  const stub = path.join(dir, 'stub-engine.js');
  fs.writeFileSync(stub, "console.log('ENV_LOG_FILE=' + process.env.CARNIVORE_LOG_FILE);\n" +
    "let n = 0; setInterval(() => { n += 1; console.log('tick ' + n); console.error('err ' + n); }, 50);\n");
  const parent = path.join(dir, 'parent.js');
  fs.writeFileSync(parent, `
    const { spawn } = require('node:child_process');
    const fs = require('node:fs');
    const [mode, spawnModule, stubPath, logFile] = process.argv.slice(2);
    const env = { ...process.env, CARNIVORE_LOG_FILE: logFile };
    if (mode === 'detached') {
      const { pid } = require(spawnModule).spawnDetachedEngine({ pythonPath: process.execPath, args: [stubPath], cwd: process.cwd(), env, logFile, banner: '=== start ===\\n' });
      process.stdout.write(JSON.stringify({ pid, parent: process.pid }) + '\\n');
      process.exit(0);
    } else {
      const child = spawn(process.execPath, [stubPath], { stdio: ['ignore', 'pipe', 'pipe'], env });
      for (const stream of [child.stdout, child.stderr]) stream.on('data', (d) => fs.appendFileSync(logFile, d));
      setTimeout(() => { process.stdout.write(JSON.stringify({ pid: child.pid, parent: process.pid }) + '\\n'); process.exit(0); }, 400);
    }
  `);
  return { dir, logs, stub, parent, log: path.join(logs, 'server.log') };
}

function runParent(s, mode) {
  const out = spawnSync(process.execPath, [s.parent, mode, path.join(macDir, 'engine', 'detached-spawn.js'), s.stub, s.log], { encoding: 'utf8', timeout: 15000 });
  assert.equal(out.status, 0, `parent failed: ${out.stderr}`);
  return JSON.parse(out.stdout.trim().split('\n').pop());
}

t('a detached stub engine survives its parent, leads its own process group and keeps writing to the log', async () => {
  const s = scene();
  const { pid, parent } = runParent(s, 'detached');
  try {
    assert.ok(alive(pid), 'the engine died with its parent');
    const [pgid, ppid] = execFileSync('ps', ['-o', 'pgid=,ppid=', '-p', String(pid)], { encoding: 'utf8' }).trim().split(/\s+/).map(Number);
    assert.equal(pgid, pid, 'the engine is not its own process group leader (detached)');
    assert.notEqual(ppid, parent, 'the engine is still a child of the exited parent');
    const before = size(s.log);
    assert.ok(await until(() => size(s.log) > before + 100), 'the log did not grow after the parent exited');
    assert.ok(alive(pid));
  } finally { try { process.kill(pid, 'SIGKILL'); } catch {} }
});

t('the file the engine writes is exactly the path passed as CARNIVORE_LOG_FILE', async () => {
  const s = scene();
  const { pid } = runParent(s, 'detached');
  try {
    assert.ok(await until(() => fs.readFileSync(s.log, 'utf8').includes('err 1')), 'stdout and stderr never reached the file');
    const text = fs.readFileSync(s.log, 'utf8');
    assert.ok(text.startsWith('=== start ==='), 'the banner is not first');
    assert.ok(text.includes(`ENV_LOG_FILE=${s.log}\n`), 'the engine did not log to the file named in its environment');
    assert.equal(fs.statSync(s.log).mode & 0o777, 0o600);
  } finally { try { process.kill(pid, 'SIGKILL'); } catch {} }
});

t('CONTROL: the old piped model dies with its parent and the log stops growing', async () => {
  const s = scene();
  const { pid } = runParent(s, 'piped');
  try {
    assert.ok(await until(() => !alive(pid), 5000), 'a piped engine survived its parent: this test cannot tell the models apart');
    const frozen = size(s.log);
    await sleep(300);
    assert.equal(size(s.log), frozen);
  } finally { try { process.kill(pid, 'SIGKILL'); } catch {} }
});

t('rotation at spawn: five backups, the live file under the cap, file 0600, folder 0700', async () => {
  const s = scene();
  fs.writeFileSync(s.log, 'L'.repeat(4000), { mode: 0o644 });
  for (let i = 1; i <= 5; i += 1) fs.writeFileSync(`${s.log}.${i}`, `old${i}`);
  const { pid } = spawnDetachedEngine({ pythonPath: process.execPath, args: [s.stub], cwd: s.dir, logFile: s.log, banner: `${'B'.repeat(199)}\n`, maxBytes: 4096, backupCount: 5, env: { ...process.env, CARNIVORE_LOG_FILE: s.log } });
  try {
    assert.equal(fs.readFileSync(`${s.log}.1`, 'utf8'), 'L'.repeat(4000));
    for (let i = 2; i <= 5; i += 1) assert.equal(fs.readFileSync(`${s.log}.${i}`, 'utf8'), `old${i - 1}`);
    assert.ok(!fs.existsSync(`${s.log}.6`), 'a sixth backup exists');
    assert.ok(size(s.log) < 4096, 'the live file was not rotated at spawn');
    assert.equal(fs.statSync(s.log).mode & 0o777, 0o600);
    assert.equal(fs.statSync(s.logs).mode & 0o777, 0o700);
  } finally { try { process.kill(pid, 'SIGKILL'); } catch {} }
});

t('only a matching version adopts; a mismatch and both unknowns never do', () => {
  assert.equal(decideAdoption({ runningVersion: '2.0.0', bundleVersion: '2.0.0' }).adopt, true);
  assert.deepEqual(['1.16.2', '', null, undefined].map((v) => decideAdoption({ runningVersion: v, bundleVersion: '2.0.0' }).adopt), [false, false, false, false]);
  assert.equal(decideAdoption({ runningVersion: '2.0.0', bundleVersion: '' }).adopt, false);
  assert.deepEqual(['mismatch', 'running-unknown', 'bundle-unknown'],
    [decideAdoption({ runningVersion: '1.0.0', bundleVersion: '2.0.0' }).outcome, decideAdoption({ bundleVersion: '2.0.0' }).outcome, decideAdoption({ runningVersion: '2.0.0' }).outcome]);
});

t('Cmd-Q leaves the engine, "Quit and Stop Engine" stops it, and ownership picks signal or route', () => {
  assert.equal(policy.ENGINE_SURVIVES_CMDQ, true);
  assert.equal(policy.quitPlan({ intent: 'app', noticeShown: true, engineSurvivesQuit: policy.ENGINE_SURVIVES_CMDQ }).stopEngine, false);
  assert.equal(policy.quitPlan({ intent: 'engine', noticeShown: true, engineSurvivesQuit: policy.ENGINE_SURVIVES_CMDQ }).stopEngine, true);
  assert.equal(decideLifecycleAction({ action: 'stop-engine', owned: true }).via, 'signal');
  const adopted = decideLifecycleAction({ action: 'stop-engine', owned: false });
  assert.equal(adopted.permitted, true);
  assert.equal(adopted.via, 'route');
  assert.equal(decideLifecycleAction({ action: 'stop', owned: false }).permitted, false, 'the plain Stop Server still refuses an adopted engine');
});

t('a teardown that cannot stop the engine calls the quit off, and the next quit tries again', async () => {
  const calls = [];
  let outcome = { cancelQuit: true };
  const handler = createQuitHandler({ teardown: async () => { calls.push('teardown'); return outcome; }, quit: () => calls.push('quit'), defer: (fn) => fn() });
  const event = { preventDefault: () => calls.push('prevent') };
  await handler(event);
  assert.deepEqual(calls, ['prevent', 'teardown']);
  outcome = null;
  await handler(event);
  assert.deepEqual(calls, ['prevent', 'teardown', 'prevent', 'teardown', 'quit']);
});

const instant = { sleep: async () => {}, pollMs: 0 };

t('shutdown route: a 200 and a freed port is stopped, signed with the tray client', async () => {
  const seen = [];
  let up = true;
  const api = { sendAuthed: async (route, body, method) => { seen.push([route, body, method]); up = false; return { reachable: true, status: 200, data: {}, error: null }; } };
  const result = await stopEngineViaRoute({ getApi: () => api, isUp: async () => up, ...instant });
  assert.deepEqual(result, { stopped: true, outcome: 'stopped' });
  assert.deepEqual(seen, [[SHUTDOWN_ROUTE, {}, 'POST']]);
  assert.equal(SHUTDOWN_ROUTE, '/api/v1/shutdown');
});

t('shutdown route through the real tray client: a 401 refreshes the token and retries exactly once', async () => {
  const posts = [];
  let verifies = 0;
  let up = true;
  const fetchImpl = async (url, init) => {
    const route = new URL(url).pathname;
    const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });
    if (route === '/api/v1/auth/verify') { verifies += 1; return reply(200, { access_token: `t${verifies}`, expires_in: 14400 }); }
    posts.push(init.headers.Authorization);
    if (posts.length === 1) return reply(401, { detail: 'revoked' });
    up = false;
    return reply(200, { success: true });
  };
  const api = new TrayApiClient({ baseUrl: 'http://127.0.0.1:5999', getOtp: () => '123456', fetchImpl });
  const result = await stopEngineViaRoute({ getApi: () => api, isUp: async () => up, ...instant });
  assert.equal(result.stopped, true);
  assert.deepEqual(posts, ['Bearer t1', 'Bearer t2']);
});

t('shutdown route unreachable, no client, or port never freed: a named failure and nothing is killed', async () => {
  const realKill = process.kill;
  const killed = [];
  process.kill = (...args) => { killed.push(args); return true; };
  try {
    const down = { sendAuthed: async () => ({ reachable: false, error: 'connection refused' }) };
    assert.deepEqual(await stopEngineViaRoute({ getApi: () => down, isUp: async () => true, ...instant }),
      { stopped: false, outcome: 'route-failed', error: 'connection refused' });
    assert.equal((await stopEngineViaRoute({ getApi: () => null, isUp: async () => true, ...instant })).outcome, 'no-api');
    let clock = 0;
    const ok = { sendAuthed: async () => ({ reachable: true }) };
    const held = await stopEngineViaRoute({ getApi: () => ok, isUp: async () => true, budgetMs: 100, pollMs: 50, sleep: async (ms) => { clock += ms; }, now: () => clock });
    assert.equal(held.outcome, 'port-still-held');
    assert.deepEqual(await stopEngineViaRoute({ getApi: () => null, isUp: async () => false, ...instant }), { stopped: true, outcome: 'already-down' });
  } finally { process.kill = realKill; }
  assert.deepEqual(killed, []);
});

t('R2-BR B1: a listener that is not provably ours gets no signed call, through the lifecycle stop too', async () => {
  let signed = 0;
  const api = { sendAuthed: async () => { signed += 1; return { reachable: true }; } };
  const refused = await stopEngineViaRoute({ getApi: () => api, isUp: async () => true, verifyHolder: async () => ({ reason: 'not_yours', holder: null }), ...instant });
  assert.equal(refused.stopped, false);
  assert.equal(refused.outcome, 'holder-refused');
  assert.equal(signed, 0);
  const { stopEngine } = require(path.join(macDir, 'engine', 'engine-lifecycle.js'));
  const manager = { ownedProcess: false, engineIsUp: async () => true, getPort: () => 59997 };
  const viaLifecycle = await stopEngine(manager, { getApi: () => api });
  assert.equal(viaLifecycle.outcome, 'holder-refused');
  assert.equal(signed, 0);
});

t('wiring: server-manager spawns through spawnDetachedEngine with no pipe, keeps CARNIVORE_LOG_FILE, and no file pattern-kills', () => {
  const manager = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(manager, /getHost\(\)\.spawnEngine\(\{/);
  assert.match(fs.readFileSync(path.join(macDir, 'engine-host', 'spawn.js'), 'utf8'), /spawnDetachedEngine\(options\)/);
  assert.doesNotMatch(manager, /stdio: \['ignore', 'pipe', 'pipe'\]/);
  assert.match(manager, /env\.CARNIVORE_LOG_FILE = this\.logFile/);
  assert.match(fs.readFileSync(path.join(macDir, 'engine', 'detached-spawn.js'), 'utf8'), /detached: true/);
  assert.match(main, /if \(serverManager\) serverManager\.beginQuit\(\);/, 'beginQuit must run on every quit, not only when the engine stops');
  assert.match(main, /plan\.stopEngine && serverManager/);
  for (const file of ['server-manager.js', 'main.js', 'engine/detached-spawn.js', 'engine/engine-stop.js', 'engine/engine-lifecycle.js']) {
    assert.doesNotMatch(fs.readFileSync(path.join(macDir, file), 'utf8'), /\b(pkill|killall)\b/, `${file} pattern-kills`);
  }
});

for (const [name, fn] of queue) {
  await fn();
  console.log(`ok - ${name}`);
}
console.log(`${queue.length} passed`);
