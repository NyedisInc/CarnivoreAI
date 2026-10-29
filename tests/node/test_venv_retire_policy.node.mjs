import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const retire = require('../../macOS/engine/venv-retire.js');
const handoff = require('../../macOS/engine/login-handoff.js');

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'r2-05-'));
}

function fixture163(home) {
  const support = path.join(home, 'Library', 'Application Support');
  const userData = path.join(support, 'cloude-code-menubar');
  const server = path.join(userData, 'server');
  fs.mkdirSync(path.join(server, 'venv', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(server, 'venv', 'bin', 'python3'), 'x');
  fs.writeFileSync(path.join(server, '.env'), 'TOTP_SECRET=a\nJWT_SECRET=b\n');
  fs.writeFileSync(path.join(server, 'config.json'), '{"a":1}');
  fs.writeFileSync(path.join(server, '.totp_paired'), '1');
  fs.writeFileSync(path.join(userData, 'menubar-settings.json'), '{}');
  const state = path.join(support, 'Carnivore');
  fs.mkdirSync(state, { recursive: true });
  fs.writeFileSync(path.join(state, 'carnivore.db'), 'SQLite format 3\0db-bytes');
  return { support, userData, server, state };
}

test('three healthy payload launches retire the venv, two do not', () => {
  const ud = tmp();
  const r1 = retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  const r2 = retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  assert.deepEqual([r1.count, r1.retire, r2.count, r2.retire], [1, false, 2, false]);
  const r3 = retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  assert.deepEqual([r3.count, r3.retire], [3, true]);
});

test('an unhealthy launch resets the count', () => {
  const ud = tmp();
  retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  assert.equal(retire.recordLaunch({ userData: ud, hasPayload: true, healthy: false }).count, 0);
  assert.equal(retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true }).retire, false);
});

test('a launch that began and never finished counts as unhealthy', () => {
  const ud = tmp();
  retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  retire.beginLaunch({ userData: ud, hasPayload: true });
  retire.beginLaunch({ userData: ud, hasPayload: true });
  assert.equal(retire.readState(ud).count, 0);
});

test('a dev install without a payload never retires and writes nothing', () => {
  const ud = tmp();
  for (let i = 0; i < 5; i += 1) {
    const r = retire.recordLaunch({ userData: ud, hasPayload: false, healthy: true });
    assert.equal(r.retire, false);
  }
  assert.deepEqual(fs.readdirSync(ud), []);
});

test('a corrupt counter file reads as zero, never as retire', () => {
  const ud = tmp();
  fs.writeFileSync(path.join(ud, retire.STATE_FILE), '{{{ not json');
  assert.equal(retire.readState(ud).count, 0);
  fs.writeFileSync(path.join(ud, retire.STATE_FILE), JSON.stringify({ count: 99 }));
  assert.equal(retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true }).retire, true);
  fs.writeFileSync(path.join(ud, retire.STATE_FILE), JSON.stringify({ count: 'many' }));
  assert.equal(retire.readState(ud).count, 0);
});

test('the upgrade keeps the pairing files together and retires only the venv after the third launch', () => {
  const home = tmp();
  const f = fixture163(home);
  const dbBefore = fs.statSync(path.join(f.state, 'carnivore.db'));
  const envBefore = fs.readFileSync(path.join(f.server, '.env'), 'utf8');

  const realHome = process.env.HOME;
  process.env.HOME = home;
  const set = [];
  try {
    const { relocateUserData } = require('../../macOS/userdata-migration.js');
    relocateUserData({ setPath: (n, p) => set.push([n, p]) });
  } finally {
    process.env.HOME = realHome;
  }
  const newUserData = path.join(f.support, 'Carnivore Menubar');
  assert.deepEqual(set, [['userData', newUserData]]);
  const server = path.join(newUserData, 'server');
  for (const name of ['.env', 'config.json', '.totp_paired']) {
    assert.ok(fs.existsSync(path.join(server, name)), `${name} moved with the directory`);
  }

  for (let i = 0; i < 2; i += 1) {
    assert.equal(retire.recordLaunch({ userData: newUserData, hasPayload: true, healthy: true }).retire, false);
    assert.ok(fs.existsSync(path.join(server, 'venv', 'bin', 'python3')), 'venv stays before the third launch');
  }
  const third = retire.recordLaunch({ userData: newUserData, hasPayload: true, healthy: true });
  assert.equal(third.retire, true);
  assert.equal(retire.retireVenv({ serverDir: server }).retired, true);

  assert.ok(!fs.existsSync(path.join(server, 'venv')));
  for (const name of ['.env', 'config.json', '.totp_paired']) assert.ok(fs.existsSync(path.join(server, name)), `${name} survives`);
  assert.equal(fs.readFileSync(path.join(server, '.env'), 'utf8'), envBefore);
  const dbAfter = fs.statSync(path.join(f.state, 'carnivore.db'));
  assert.deepEqual([dbAfter.ino, dbAfter.size, dbAfter.mtimeMs], [dbBefore.ino, dbBefore.size, dbBefore.mtimeMs]);
});

test('retireVenv removes only a real venv folder: never a symlink, never anything else', () => {
  const root = tmp();
  const target = path.join(root, 'elsewhere');
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, 'keep'), '1');
  const server = path.join(root, 'server');
  fs.mkdirSync(server);
  fs.symlinkSync(target, path.join(server, 'venv'));
  const r = retire.retireVenv({ serverDir: server });
  assert.equal(r.retired, false);
  assert.ok(fs.existsSync(path.join(target, 'keep')));
  assert.equal(retire.retireVenv({ serverDir: path.join(root, 'nothing') }).retired, false);
});

function fakeInstaller(enabled) {
  const calls = [];
  return { calls, isEnabled: () => enabled, dropPlistFile: () => calls.push('drop') };
}

test('the previous launch-at-login choice is recorded and, once carried, never overwritten', () => {
  const ud = tmp();
  const a = handoff.recordPreviousChoice({ userData: ud, installer: fakeInstaller(true), windowAtLogin: true });
  assert.equal(a.launchAtLogin, true);
  assert.equal(a.windowAtLogin, true);
  fs.writeFileSync(path.join(ud, handoff.RECORD_FILE), JSON.stringify({ ...a, carriedBy: 'R2-06' }));
  const b = handoff.recordPreviousChoice({ userData: ud, installer: fakeInstaller(false), windowAtLogin: false });
  assert.equal(b.launchAtLogin, true, 'a carried record is the user\'s choice, frozen');
  assert.equal(handoff.readRecord(ud).carriedBy, 'R2-06');
});

test('the LaunchAgent stays until the login service exists, and is never removed without a record', () => {
  const ud = tmp();
  const inst = fakeInstaller(true);
  handoff.recordPreviousChoice({ userData: ud, installer: inst, windowAtLogin: false });
  assert.equal(handoff.LOGIN_SERVICE_READY, false);
  assert.deepEqual(handoff.retireLaunchAgent({ userData: ud, installer: inst }), { retired: false, reason: 'login-service-not-ready' });
  assert.deepEqual(inst.calls, []);
  fs.writeFileSync(path.join(ud, handoff.RECORD_FILE), JSON.stringify({ ...handoff.readRecord(ud), carriedBy: 'R2-06' }));
  const ready = handoff.retireLaunchAgent({ userData: ud, installer: inst, ready: true });
  assert.equal(ready.retired, true);
  assert.deepEqual(inst.calls, ['drop']);
  const bare = tmp();
  assert.equal(handoff.retireLaunchAgent({ userData: bare, installer: inst, ready: true }).reason, 'no-record');
  assert.deepEqual(inst.calls, ['drop']);
});


test('retiring the venv removes the deps-hash first, so a rebuilt empty venv is never trusted', () => {
  const f = fixture163(tmp());
  fs.writeFileSync(path.join(f.server, '.deps-hash'), 'abc');
  const order = [];
  const realRm = fs.rmSync;
  fs.rmSync = (p, o) => { order.push(path.basename(p)); return realRm(p, o); };
  try {
    assert.equal(retire.retireVenv({ serverDir: f.server }).retired, true);
  } finally {
    fs.rmSync = realRm;
  }
  assert.equal(fs.existsSync(path.join(f.server, '.deps-hash')), false);
  assert.equal(fs.existsSync(path.join(f.server, 'venv')), false);
  assert.deepEqual(order.slice(0, 2), ['.deps-hash', 'venv']);
});

test('a launch that adopted an engine is neither counted nor reset', () => {
  const ud = tmp();
  retire.recordLaunch({ userData: ud, hasPayload: true, healthy: true });
  retire.beginLaunch({ userData: ud, hasPayload: true });
  const r = retire.recordLaunch({ userData: ud, hasPayload: true, healthy: null });
  assert.deepEqual([r.count, r.retire], [1, false]);
  assert.equal(retire.readState(ud).pending, false);
  retire.beginLaunch({ userData: ud, hasPayload: true });
  assert.equal(retire.readState(ud).count, 1, 'an adopted launch does not lose the count next time');
});

test('a counter write that fails never throws out of beginLaunch', () => {
  const ud = path.join(tmp(), 'ro');
  fs.mkdirSync(ud, { mode: 0o500 });
  if (process.getuid && process.getuid() === 0) return;
  assert.deepEqual(retire.beginLaunch({ userData: ud, hasPayload: true }), { count: 0 });
});

test('the login record follows the owner until the login service carries it', () => {
  const ud = tmp();
  handoff.recordPreviousChoice({ userData: ud, installer: fakeInstaller(false), windowAtLogin: false });
  const later = handoff.recordPreviousChoice({ userData: ud, installer: fakeInstaller(true), windowAtLogin: true });
  assert.equal(later.launchAtLogin, true);
  assert.equal(later.windowAtLogin, true);
  fs.writeFileSync(path.join(ud, handoff.RECORD_FILE), JSON.stringify({ ...later, carriedBy: 'R2-06' }));
  const kept = handoff.recordPreviousChoice({ userData: ud, installer: fakeInstaller(false), windowAtLogin: false });
  assert.equal(kept.launchAtLogin, true, 'once carried, the record is frozen');
});

test('the plist is never removed until the login service says it carried the choice', () => {
  const ud = tmp();
  const inst = fakeInstaller(true);
  handoff.recordPreviousChoice({ userData: ud, installer: inst, windowAtLogin: false });
  assert.equal(handoff.retireLaunchAgent({ userData: ud, installer: inst, ready: true }).reason, 'not-carried');
  assert.deepEqual(inst.calls, []);
});
