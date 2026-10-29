
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const V = require(process.env.UPDATE_VERIFY_MODULE || '../../macOS/update-verify.js');
const A = require('../../macOS/auto-update.js');

let passes = 0, failures = 0;
async function test(name, fn) {
  try { await fn(); passes++; }
  catch (e) { failures++; console.error(`FAIL: ${name}\n  ${e.stack || e.message}`); }
}

const TEAM = 'ARD6KN4BX4';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cloude-update-verify-'));

function fakeRun(o = {}) {
  const calls = [];
  const run = async (cmd, args) => {
    calls.push([cmd, ...args]);
    if (cmd === '/usr/bin/ditto') {
      if (o.failDitto) throw new Error('ditto: bad zip');
      const layout = o.layout ?? Array.from({ length: o.apps ?? 1 }, (_, i) => `Carnivore${i || ''}.app`);
      for (const entry of layout) {
        const link = entry.startsWith('link:');
        const rel = link ? entry.slice(5) : entry;
        fs.mkdirSync(path.dirname(path.join(args[3], rel)), { recursive: true });
        if (link) fs.symlinkSync('/tmp', path.join(args[3], rel)); else fs.mkdirSync(path.join(args[3], rel));
      }
      return { stdout: '', stderr: '' };
    }
    if (cmd === '/usr/bin/codesign' && args[0] === '-dv') {
      return { stdout: '', stderr: `Identifier=ai.carnivore.menubar\nTeamIdentifier=${o.team ?? TEAM}\n` };
    }
    if (cmd === '/usr/bin/codesign' && args.some((a) => a.startsWith('-R='))) {
      if (o.failRequirement) throw new Error('does not satisfy its designated Requirement');
      return { stdout: '', stderr: '' };
    }
    if (cmd === '/usr/bin/codesign') {
      if (o.failVerify) throw new Error('a sealed resource is missing or invalid');
      return { stdout: '', stderr: '' };
    }
    if (cmd === '/usr/bin/plutil') {
      const key = args[1];
      if (key === 'CFBundleIdentifier') return { stdout: (o.bundleId ?? 'ai.carnivore.menubar') + '\n', stderr: '' };
      if (key === 'CarnivoreBuildPurpose') {
        if (o.purpose === null) throw new Error('No value at that key path');
        return { stdout: (o.purpose ?? 'release') + '\n', stderr: '' };
      }
      if (key === 'CarnivoreVersion') {
        if (o.carnivoreVersion === undefined) throw new Error('No value at that key path');
        return { stdout: o.carnivoreVersion + '\n', stderr: '' };
      }
      if (key === 'CFBundleShortVersionString') return { stdout: (o.version ?? '2.0.0') + '\n', stderr: '' };
    }
    throw new Error('unexpected ' + cmd);
  };
  return { run, calls };
}
function leftovers() {
  return fs.readdirSync(root).filter((n) => n.startsWith('carnivore-update-verify-'));
}
const verify = (o, current = '1.16.3', currentPurpose = null) =>
  V.verifyStagedUpdate({ zipPath: '/x/update.zip', currentVersion: current, currentPurpose, run: fakeRun(o).run, tmpdir: root });

await test('a good team and a greater version pass, and the temp dir is gone', async () => {
  const r = await verify({ version: '2.0.0-beta.1' });
  assert.deepEqual(r, { ok: true, reason: null, version: '2.0.0-beta.1' });
  assert.deepEqual(leftovers(), []);
});

await test('a wrong team is refused (the old team, an ad hoc "not set", and a failed requirement)', async () => {
  for (const o of [{ team: 'MDH8UQ6H46' }, { team: 'not' }, { failRequirement: true }]) {
    const r = await verify({ ...o, version: '9.0.0' });
    assert.equal(r.ok, false, JSON.stringify(o));
    assert.match(r.reason, /team|Requirement/i);
  }
  assert.deepEqual(leftovers(), []);
});

await test('an equal version and a lower version are refused', async () => {
  assert.equal((await verify({ version: '1.16.3' })).ok, false);
  assert.equal((await verify({ version: '1.16.2' })).ok, false);
  assert.equal((await verify({ version: '2.0.0' }, '2.0.0')).ok, false, '2.0.0 offered over 2.0.0');
  assert.match((await verify({ version: '2.0.0' }, '2.0.0')).reason, /not newer/);
});

await test('the order 1.16.3 < 2.0.0-beta.1 < 2.0.0-beta.2 < 2.0.0 holds in both directions', async () => {
  const order = ['1.16.3', '2.0.0-beta.1', '2.0.0-beta.2', '2.0.0'];
  for (let i = 0; i < order.length; i++) {
    for (let j = 0; j < order.length; j++) {
      const r = await verify({ version: order[j] }, order[i]);
      assert.equal(r.ok, j > i, `${order[j]} over ${order[i]}`);
      assert.equal(V.isStrictlyNewer(order[j], order[i]), j > i, `isStrictlyNewer ${order[j]} ${order[i]}`);
    }
  }
  assert.equal(V.isStrictlyNewer('2.0.0-beta.10', '2.0.0-beta.9'), true, 'numeric prerelease parts, not text');
});

await test('CarnivoreVersion wins over the bundle key; an invalid version string is refused', async () => {
  assert.equal((await verify({ version: '0.0.1', carnivoreVersion: '2.0.0-beta.1' })).version, '2.0.0-beta.1');
  assert.equal((await verify({ version: 'banana' })).ok, false);
  assert.equal((await verify({ version: '2.0.0' }, 'banana')).ok, false);
  assert.equal((await verify({ version: '2.0.0.1' })).ok, false, 'four dotted numbers are not semver');
});

await test('not exactly one app, a failing codesign --verify and a failing ditto are refused', async () => {
  assert.equal((await verify({ apps: 0, version: '9.0.0' })).ok, false);
  assert.equal((await verify({ apps: 2, version: '9.0.0' })).ok, false);
  assert.equal((await verify({ failVerify: true, version: '9.0.0' })).ok, false);
  assert.equal((await verify({ failDitto: true, version: '9.0.0' })).ok, false);
  assert.equal((await V.verifyStagedUpdate({ zipPath: null, currentVersion: '1.0.0', tmpdir: root })).ok, false);
  assert.deepEqual(leftovers(), [], 'the temp dir is removed on every path');
});

await test('the signature is checked strictly, deep, and against the team requirement', async () => {
  const f = fakeRun({ version: '2.0.0' });
  await V.verifyStagedUpdate({ zipPath: '/x/u.zip', currentVersion: '1.16.3', run: f.run, tmpdir: root });
  const flat = f.calls.map((c) => c.join(' '));
  assert.ok(flat.some((c) => /^\/usr\/bin\/codesign --verify --deep --strict /.test(c)), 'deep strict verify');
  assert.ok(flat.some((c) => c.includes('leaf[subject.OU] = "ARD6KN4BX4"')), 'team requirement');
});

await test('finding 1: a hidden top-level app, a nested app, a symlink or two bundles are refused', async () => {
  const bad = [
    ['.Carnivore.app', 'x/Carnivore.app'],
    ['x/Carnivore.app'],
    ['Carnivore.app', 'x/Carnivore.app'],
    ['.Carnivore.app'],
    ['link:Carnivore.app'],
    ['Carnivore.app', 'Other.app']
  ];
  for (const layout of bad) {
    const r = await verify({ layout, version: '9.0.0' });
    assert.equal(r.ok, false, JSON.stringify(layout));
  }
  assert.equal((await verify({ layout: ['Carnivore.app', 'notes.txt'], version: '9.0.0' })).ok, true, 'a stray file is no bundle');
  assert.deepEqual(leftovers(), []);
});

await test('finding 1: the bundle identifier must be the running app\'s', async () => {
  const r = await verify({ bundleId: 'com.example.other', version: '9.0.0' });
  assert.equal(r.ok, false);
  assert.match(r.reason, /ai\.carnivore\.menubar/);
});

await test('finding 2: the requirement is the full designated requirement (identifier, Developer ID chain, team)', async () => {
  const f = fakeRun({ version: '2.0.0' });
  await V.verifyStagedUpdate({ zipPath: '/x/u.zip', currentVersion: '1.16.3', run: f.run, tmpdir: root });
  const req = f.calls.map((c) => c.find((a) => typeof a === 'string' && a.startsWith('-R='))).find(Boolean);
  assert.ok(req.includes('identifier "ai.carnivore.menubar"'), req);
  assert.ok(req.includes('certificate 1[field.1.2.840.113635.100.6.2.6]'), req);
  assert.ok(req.includes('certificate leaf[field.1.2.840.113635.100.6.1.13]'), req);
});

await test('finding 8: every tool runs by absolute path with a fixed PATH', async () => {
  const f = fakeRun({ version: '2.0.0' });
  await V.verifyStagedUpdate({ zipPath: '/x/u.zip', currentVersion: '1.16.3', run: f.run, tmpdir: root });
  assert.ok(f.calls.length > 4);
  assert.ok(f.calls.every((c) => c[0].startsWith('/usr/bin/')), JSON.stringify(f.calls.map((c) => c[0])));
});

await test('finding 4: only a release build is accepted; a test build or a keyless newer build is refused', async () => {
  assert.equal((await verify({ version: '9.0.0', purpose: 'release' })).ok, true);
  for (const purpose of ['vm-test', 'e2e-test', 'update-proof', 'banana', null]) {
    const r = await verify({ version: '9.0.0', purpose });
    assert.equal(r.ok, false, String(purpose));
  }
});

await test('F9: an update-proof build accepts an update-proof update (and only that); every other pairing still needs a release build', async () => {
  assert.equal((await verify({ version: '9.0.0', purpose: 'update-proof' }, '1.16.3', 'update-proof')).ok, true);
  for (const [purpose, current] of [['vm-test', 'update-proof'], ['update-proof', 'release'], ['update-proof', 'vm-test'], ['update-proof', null], ['banana', 'update-proof'], [null, 'update-proof']]) {
    const r = await verify({ version: '9.0.0', purpose }, '1.16.3', current);
    assert.equal(r.ok, false, `${purpose} over ${current}`);
  }
  assert.equal((await verify({ version: '9.0.0', purpose: 'release' }, '1.16.3', 'update-proof')).ok, true);
});

function fakeUpdater() {
  const u = new EventEmitter();
  Object.assign(u, { installs: 0, setFeedURL() {}, quitAndInstall() { this.installs++; }, async checkForUpdates() {}, async downloadUpdate() {} });
  return u;
}
async function readyController(o, current = '1.16.3') {
  const u = fakeUpdater();
  const order = [];
  u.quitAndInstall = () => order.push('quitAndInstall');
  const f = fakeRun(o);
  const c = A.createUpdateController({
    updater: u, getFeed: () => ({ url: 'https://u.example/app', source: 'env', error: null }),
    verifyUpdate: (zipPath) => V.verifyStagedUpdate({ zipPath, currentVersion: current, run: f.run, tmpdir: root }),
    beforeInstall: async () => { order.push('beforeInstall'); }, onChange: () => {}
  });
  u.emit('update-downloaded', { version: o.version, downloadedFile: '/x/u.zip' });
  return { c, order };
}

await test('a refused update never stops the engine or installs, and the state is update_refused', async () => {
  for (const o of [{ team: 'MDH8UQ6H46', version: '2.0.0' }, { version: '1.16.3' }, { version: '1.16.2' }]) {
    const { c, order } = await readyController(o);
    assert.equal(await c.install(), false);
    assert.deepEqual(order, [], JSON.stringify(o));
    assert.equal(c.getState().state, A.STATE_UPDATE_REFUSED);
    assert.ok(c.getState().detail);
  }
});

await test('an accepted update stops the engine, then installs', async () => {
  const { c, order } = await readyController({ version: '2.0.0-beta.1' });
  assert.equal(await c.install(), true);
  assert.deepEqual(order, ['beforeInstall', 'quitAndInstall']);
});

await test('a controller with no verifier configured fails closed', async () => {
  const u = fakeUpdater();
  const c = A.createUpdateController({ updater: u, getFeed: () => ({ url: 'https://u.example/a', source: 'env', error: null }) });
  u.emit('update-downloaded', { version: '9.9.9', downloadedFile: '/x/u.zip' });
  assert.equal(await c.install(), false);
  assert.equal(u.installs, 0);
});

fs.rmSync(root, { recursive: true, force: true });
console.log(`${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
