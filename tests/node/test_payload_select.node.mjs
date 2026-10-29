import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { payloadArch, payloadRoot, TREE_ARCHES, resolvePayload, enginePath, applyPayloadEnv, payloadEngineEnv, pycacheEnv, stageTmux } = require('../../macOS/engine/payload-select.js');

test('arm64 picks arm64', () => {
  assert.equal(payloadArch('arm64'), 'arm64');
  assert.equal(payloadRoot('/R', 'arm64'), '/R/payload/payload-arm64');
});

test('x64 picks x86_64', () => {
  assert.equal(payloadArch('x64'), 'x86_64');
  assert.equal(payloadRoot('/R', 'x64'), '/R/payload/payload-x86_64');
});

test('an arch with no tree throws, never a default', () => {
  assert.throws(() => payloadArch('ia32'), /no engine payload/);
});

test('this process arch resolves to one of the built trees', () => {
  assert.ok(TREE_ARCHES.includes(payloadArch()));
});

function fixtureResources(arch, withTmux = true) {
  const res = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-payload-sel-'));
  const root = path.join(res, 'payload', `payload-${arch}`);
  fs.mkdirSync(path.join(root, 'python', 'bin'), { recursive: true });
  fs.mkdirSync(path.join(root, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(root, 'python', 'bin', 'python3'), '#!/bin/sh\n', { mode: 0o755 });
  if (withTmux) fs.writeFileSync(path.join(root, 'bin', 'tmux'), '#!/bin/sh\n', { mode: 0o755 });
  return res;
}

test('a bundle with a tree for this arch resolves it; arm64 never picks the x86_64 tree', () => {
  const res = fixtureResources('arm64');
  const p = resolvePayload(res, 'arm64');
  assert.equal(p.python, path.join(res, 'payload', 'payload-arm64', 'python', 'bin', 'python3'));
  assert.equal(p.tmux, path.join(res, 'payload', 'payload-arm64', 'bin', 'tmux'));
  assert.equal(resolvePayload(res, 'x64'), null);
});

test('no payload, a half-built tree, an empty path and an unknown arch all fall back (null)', () => {
  assert.equal(resolvePayload(fs.mkdtempSync(path.join(os.tmpdir(), 'cc-payload-none-')), 'arm64'), null);
  assert.equal(resolvePayload(fixtureResources('arm64', false), 'arm64'), null);
  assert.equal(resolvePayload('', 'arm64'), null);
  assert.equal(resolvePayload(fixtureResources('arm64'), 'ia32'), null);
});

test('the engine PATH: payload bin first, Homebrew kept after the inherited PATH, payload python never on it', () => {
  const payload = { binDir: '/P/bin', pythonBinDir: '/P/python/bin' };
  const finder = enginePath(payload, { inheritedPath: '/usr/bin:/bin:/usr/sbin:/sbin' });
  assert.equal(finder, '/P/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin');
  const withUser = enginePath(payload, { inheritedPath: '/Users/a/.local/bin:/usr/bin', shellBinDir: '/S/bin' });
  assert.equal(withUser, '/P/bin:/S/bin:/Users/a/.local/bin:/usr/bin:/opt/homebrew/bin:/usr/local/bin:/bin:/usr/sbin:/sbin');
  assert.ok(!enginePath(payload, { inheritedPath: '' }).includes('/P/python/bin'), 'python/bin would shadow the user python and pip');
  assert.ok(enginePath(payload, { inheritedPath: '' }).endsWith('/usr/sbin:/sbin'));
});

test('stageTmux re-stages a staged copy whose bytes no longer match its hash key (R2-BR N5)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-stage-'));
  const src = path.join(dir, 'a');
  fs.writeFileSync(src, '#!/bin/sh\necho one\n', { mode: 0o755 });
  const stage = path.join(dir, 'ud', 'tmux');
  const staged = stageTmux(src, stage);
  fs.writeFileSync(staged, '#!/bin/sh\necho swapped\n', { mode: 0o755 });
  assert.equal(stageTmux(src, stage), staged);
  assert.equal(fs.readFileSync(staged, 'utf8'), '#!/bin/sh\necho one\n', 'the swapped copy was replaced from the payload');
});

test('the payload env names the bundled tmux and python and drops PYTHONHOME and PYTHONPATH', () => {
  const cache = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cc-pyc-')), 'pycache');
  const env = applyPayloadEnv({ python: '/P/python/bin/python3', tmux: '/P/bin/tmux' }, { A: '1', PYTHONHOME: '/x', PYTHONPATH: '/y' }, undefined, cache);
  assert.deepEqual(env, { A: '1', CARNIVORE_BUNDLED_TMUX: '/P/bin/tmux', CARNIVORE_PAYLOAD_PYTHON: '/P/python/bin/python3', PYTHONNOUSERSITE: '1', PYTHONPYCACHEPREFIX: cache });
});

test('the engine env points python bytecode at a 0700 cache folder outside the bundle', () => {
  const cache = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cc-pyc-')), 'a', 'pycache');
  const env = payloadEngineEnv({ python: '/P/python/bin/python3', tmux: '/P/bin/tmux', binDir: '/P/bin' }, { PATH: '/usr/bin' }, '/S/bin', undefined, cache);
  assert.equal(env.PYTHONPYCACHEPREFIX, cache);
  assert.equal(env.PYTHONDONTWRITEBYTECODE, undefined);
  assert.equal(fs.statSync(cache).mode & 0o777, 0o700);
});

test('with no usable cache folder the env turns bytecode writing off instead', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-pyc-'));
  const blocker = path.join(dir, 'file');
  fs.writeFileSync(blocker, 'x');
  assert.deepEqual(pycacheEnv(path.join(blocker, 'pycache')), { PYTHONDONTWRITEBYTECODE: '1' });
  const env = applyPayloadEnv({ python: '/P/python/bin/python3', tmux: '/P/bin/tmux' }, {}, undefined, path.join(blocker, 'pycache'));
  assert.equal(env.PYTHONDONTWRITEBYTECODE, '1');
  assert.equal(env.PYTHONPYCACHEPREFIX, undefined);
});

test('stageTmux copies the bundled tmux to a stable content-keyed path under userData and keeps old copies', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-stage-'));
  const mk = (name, body) => { const f = path.join(dir, name); fs.writeFileSync(f, body, { mode: 0o755 }); return f; };
  const one = stageTmux(mk('a', '#!/bin/sh\necho one\n'), path.join(dir, 'ud', 'tmux'));
  const two = stageTmux(mk('b', '#!/bin/sh\necho two\n'), path.join(dir, 'ud', 'tmux'));
  assert.notEqual(one, two);
  assert.ok(one.startsWith(path.join(dir, 'ud', 'tmux')) && fs.statSync(one).mode & 0o111, 'staged copy is executable');
  assert.ok(fs.existsSync(one) && fs.existsSync(two), 'the older copy stays: a live server may still run it');
  assert.equal(stageTmux(path.join(dir, 'a'), path.join(dir, 'ud', 'tmux')), one, 'same bytes, same path');
  assert.equal(stageTmux('/nonexistent/tmux', path.join(dir, 'ud', 'tmux')), '/nonexistent/tmux', 'a failed copy falls back');
});

function managerFor(res) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-sm-ud-'));
  const fake = { app: { isPackaged: true, getAppPath: () => path.join(res, 'app.asar'), getPath: () => userData, getVersion: () => '0.0.0' } };
  const Module = require('node:module');
  if (!Module._load.fakesElectron) {
    const load = Module._load;
    Module._load = function patched(request, ...rest) {
      return request === 'electron' ? globalThis.__fakeElectron : load.call(this, request, ...rest);
    };
    Module._load.fakesElectron = true;
  }
  globalThis.__fakeElectron = fake;
  delete require.cache[require.resolve('../../macOS/server-manager.js')];
  const ServerManager = require('../../macOS/server-manager.js');
  return new ServerManager();
}

test('ServerManager boots on the payload python and PATH when the bundle carries a tree', () => {
  const arch = payloadArch();
  const res = fixtureResources(arch);
  const sm = managerFor(res);
  const p = resolvePayload(res);
  assert.equal(sm.pythonPath, p.python);
  const env = sm.engineBaseEnv('/S/bin', { PATH: '/opt/homebrew/bin:/usr/bin', PYTHONPATH: '/y' });
  assert.equal(env.PATH.split(':')[0], p.binDir);
  assert.ok(env.CARNIVORE_BUNDLED_TMUX.startsWith(env.CARNIVORE_TMUX_STAGE_DIR), 'engine is told the staged, not the in-bundle, tmux');
  assert.ok(fs.existsSync(env.CARNIVORE_BUNDLED_TMUX));
  assert.equal(env.CARNIVORE_PAYLOAD_PYTHON, p.python);
  assert.equal(env.PYTHONPATH, undefined);
});

test('ServerManager keeps today\'s interpreter and Homebrew PATH when the bundle has no payload', () => {
  const sm = managerFor(fs.mkdtempSync(path.join(os.tmpdir(), 'cc-sm-none-')));
  assert.equal(sm.payload, null);
  assert.ok(!sm.pythonPath.includes('payload-'));
  const env = sm.engineBaseEnv('/S/bin', { PATH: '/usr/bin' });
  assert.equal(env.PATH, '/S/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin');
  assert.equal(env.CARNIVORE_BUNDLED_TMUX, undefined);
  assert.equal(env.CARNIVORE_PAYLOAD_PYTHON, undefined);
});

test('bootstrap with a payload needs no venv, no lock and no system Python (fast path ready)', async () => {
  const res = fixtureResources(payloadArch());
  const serverDir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cc-bs-')), 'server');
  fs.mkdirSync(serverDir, { recursive: true });
  fs.writeFileSync(path.join(serverDir, '.env'), 'TOTP_SECRET=ABC\n');
  fs.writeFileSync(path.join(serverDir, 'config.json'), '{}');
  const { bootstrapIfNeeded } = require('../../macOS/bootstrap.js');
  const result = await bootstrapIfNeeded({ serverDir, bundleResourcesDir: res, isPackaged: false, onStateChange: () => {} });
  assert.equal(result.status, 'ready');
  assert.ok(!fs.existsSync(path.join(serverDir, 'venv')));
});

const { cacheKey, ensureTree, KEY_FILE } = require('../../macOS/scripts/payload-cache.js');

function recipeFixture(lock = 'lock-a') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-pc-recipe-'));
  fs.writeFileSync(path.join(dir, 'runtime.lock'), lock);
  fs.writeFileSync(path.join(dir, 'runtime.in'), 'in');
  fs.writeFileSync(path.join(dir, 'build-payload.sh'), 'recipe');
  return dir;
}

function fakeBuild() {
  const b = { runs: 0, fn(tmpOut) { b.runs += 1; const t = path.join(tmpOut, 'payload-arm64'); fs.mkdirSync(t, { recursive: true }); fs.writeFileSync(path.join(t, 'PAYLOAD.json'), '{}'); } };
  return b;
}

test('payload cache: same inputs reuse, a changed lock byte, a missing key file and the force variable rebuild', () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-pc-out-'));
  const recipe = recipeFixture();
  const pins = '{"pins":1}';
  const key = cacheKey('arm64', { payloadDir: recipe, pins });
  const b = fakeBuild();
  const go = (k, force = false) => ensureTree({ arch: 'arm64', out, key: k, build: b.fn, force });
  assert.equal(go(key), false);
  assert.equal(b.runs, 1);
  assert.equal(fs.readFileSync(path.join(out, 'payload-arm64', KEY_FILE), 'utf8').trim(), key);
  assert.equal(go(key), true, 'same inputs reuse');
  assert.equal(b.runs, 1);
  fs.writeFileSync(path.join(recipe, 'runtime.lock'), 'lock-b');
  const key2 = cacheKey('arm64', { payloadDir: recipe, pins });
  assert.notEqual(key2, key);
  assert.equal(go(key2), false, 'a changed lock byte rebuilds');
  assert.equal(b.runs, 2);
  assert.notEqual(cacheKey('arm64', { payloadDir: recipe, pins: '{"pins":2}' }), key2, 'a moved pin changes the key');
  assert.notEqual(cacheKey('x86_64', { payloadDir: recipe, pins }), key2, 'the arch changes the key');
  assert.equal(go(key2, true), false, 'the force variable rebuilds');
  assert.equal(b.runs, 3);
  fs.rmSync(path.join(out, 'payload-arm64', KEY_FILE));
  assert.equal(go(key2), false, 'a missing key file rebuilds');
  assert.equal(b.runs, 4);
  assert.deepEqual(fs.readdirSync(out), ['payload-arm64'], 'no temp folder left behind');
});

test('payload cache: a build that throws leaves no entry at the final path', () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-pc-out-'));
  assert.throws(() => ensureTree({ arch: 'arm64', out, key: 'k', build: (t) => { fs.mkdirSync(path.join(t, 'payload-arm64')); throw new Error('boom'); } }), /boom/);
  assert.deepEqual(fs.readdirSync(out), []);
});

test('payload: Reinstall Server Environment leaves the payload python alone and diagnostics run on it', async () => {
  const { reinstallEnv, readDiagnostics } = require('../../macOS/tray-menu/actions/troubleshoot.js');
  const boxes = [];
  let started = false;
  const sm = {
    payload: { python: '/P/python/bin/python3' }, pythonPath: '/P/python/bin/python3', baseDir: '/S', processPid: null,
    getState: () => 'stopped', isProcessRunning: () => false, findPython: () => '/opt/homebrew/bin/python3',
    resetSupervisor() {}, async start() { started = true; },
  };
  const ctx = { serverManager: sm, t: (key) => key, fs: { existsSync: () => true, renameSync() { throw new Error('moved a venv'); } }, refresh() {},
    dialog: { showErrorBox: (...a) => boxes.push(a), showMessageBox: async (o) => { boxes.push(o); return { response: 1 }; } } };
  await reinstallEnv(ctx);
  assert.equal(sm.pythonPath, '/P/python/bin/python3');
  assert.equal(started, false);
  assert.equal(boxes.length, 1, 'tells the user there is nothing to rebuild');

  const ran = [];
  await readDiagnostics({ serverManager: sm, data: { api: () => null }, execFile: (py, _a, _o, cb) => { ran.push(py); cb(null, 'ok'); } });
  assert.deepEqual(ran, ['/P/python/bin/python3']);
});

test('stageTmux reads the bundled tmux once per call when the staged copy already matches (R2-HYGIENE 2)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-once-'));
  const src = path.join(dir, 'tmux-src');
  fs.writeFileSync(src, '#!/bin/sh\necho once\n', { mode: 0o755 });
  const stage = path.join(dir, 'ud', 'tmux');
  stageTmux(src, stage);
  const real = fs.readFileSync;
  let reads = 0;
  fs.readFileSync = function patched(file, ...rest) { if (file === src) reads += 1; return real.call(this, file, ...rest); };
  try { stageTmux(src, stage); } finally { fs.readFileSync = real; }
  assert.equal(reads, 1, 'the payload tmux is hashed once');
});

test('the diagnostics fallback runs the payload python with the bytecode cache env, and a venv python without', async () => {
  const { readDiagnostics } = require('../../macOS/tray-menu/actions/troubleshoot.js');
  const seen = [];
  const mk = (payload) => ({
    data: { api: () => null }, serverManager: { baseDir: '/S', payload },
    execFile: (py, args, opts, cb) => { seen.push({ py, env: opts.env }); cb(null, '{}'); },
  });
  const realHome = process.env.HOME;
  process.env.HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-home-'));
  try {
    await readDiagnostics(mk({ python: '/P/python3', tmux: '/P/tmux' }));
  } finally { process.env.HOME = realHome; }
  await readDiagnostics(mk(null));
  assert.ok(seen[0].env && (seen[0].env.PYTHONPYCACHEPREFIX || seen[0].env.PYTHONDONTWRITEBYTECODE));
  assert.equal(seen[1].env, undefined);
});
