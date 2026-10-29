
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
const moduleUnderTest = path.join(repo, 'macOS', 'scripts', 'signing-keychain.js');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'signing-env-import-'));
const bin = path.join(tmp, 'bin');
const state = path.join(tmp, 'state');
const LOGIN = path.join(tmp, 'login.keychain-db');
const ANOTHER = path.join(tmp, 'added-mid-run.keychain-db');
const P12 = path.join(tmp, 'dummy.p12');
const SHA = 'B'.repeat(40);
fs.mkdirSync(bin);
for (const f of [LOGIN, ANOTHER]) fs.writeFileSync(f, '');
fs.writeFileSync(P12, 'not a real p12');

const SECURITY = String.raw`#!/usr/bin/env node
const fs = require('fs');
const S = process.env.FAKE_STATE;
const rd = (f, d = '') => { try { return fs.readFileSync(S + '/' + f, 'utf8'); } catch { return d; } };
const list = () => rd('list').split('\n').filter(Boolean);
const record = (r) => fs.appendFileSync(S + '/calls.jsonl', JSON.stringify(r) + '\n');
const bad = (m) => fs.appendFileSync(S + '/violations.log', m + '\n');
function tokenize(line) {
  const out = []; let cur = null, q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '\\' && i + 1 < line.length) { cur = (cur || '') + line[++i]; continue; }
    if (c === '"') { q = !q; cur = cur || ''; continue; }
    if (!q && /\s/.test(c)) { if (cur !== null) { out.push(cur); cur = null; } continue; }
    cur = (cur || '') + c;
  }
  if (cur !== null) out.push(cur);
  return out;
}
function exec(a) {
  const cmd = a[0];
  if (process.env.FAKE_FAIL === cmd) { console.error('security: fake ' + cmd + ' failure'); return 1; }
  const kc = process.env.FAKE_TEMP_KC_RE && a.find((x) => new RegExp(process.env.FAKE_TEMP_KC_RE).test(x));
  if ((cmd === 'lock-keychain' || cmd === 'delete-keychain') && kc && list().includes(kc)) bad(cmd + ' while the keychain is still on the search list');
  switch (cmd) {
    case 'list-keychains': {
      const s = a.indexOf('-s');
      if (s < 0) { for (const p of list()) console.log('    "' + p + '"'); return 0; }
      fs.writeFileSync(S + '/list', a.slice(s + 1).join('\n') + '\n'); return 0;
    }
    case 'delete-keychain':
      // Simulates a second signal arriving while the first one's cleanup is still running.
      if (process.env.FAKE_SIGNAL_ON_DELETE) process.kill(process.ppid, process.env.FAKE_SIGNAL_ON_DELETE);
      return 0;
    case 'find-identity': console.log('  1) ' + process.env.FAKE_SHA + ' "Carnivore Development" (CSSMERR_TP_NOT_TRUSTED)'); return 0;
    default: return 0;
  }
}
const argv = process.argv.slice(2);
if (argv[0] === '-i') {
  const stdin = fs.readFileSync(0, 'utf8');
  const lines = stdin.split('\n').filter((l) => l.trim());
  let rc = 0;
  const cmds = lines.map(tokenize);
  record({ argv, stdin, cmds });
  for (const c of cmds) rc = exec(c);
  process.exit(rc);
}
record({ argv, stdin: '', cmds: [] });
process.exit(exec(argv));
`;
fs.writeFileSync(path.join(bin, 'security'), SECURITY, { mode: 0o755 });

const DRIVER = path.join(tmp, 'driver.js');
fs.writeFileSync(DRIVER, `
const fs = require('fs');
const { importIdentityFromEnv } = require(${JSON.stringify(moduleUnderTest)});
(() => { try {
  const got = importIdentityFromEnv();
  fs.writeFileSync(process.env.FAKE_STATE + '/keychain', got.keychain);
  if (process.env.DRIVER_RAISE) {
    // Keep the loop alive and signal ourselves, as a terminal hangup or Ctrl-C would mid-pack.
    setTimeout(() => {}, 15000);
    process.kill(process.pid, process.env.DRIVER_RAISE);
    return;
  }
  if (process.env.DRIVER_ADD_MIDRUN) fs.appendFileSync(process.env.FAKE_STATE + '/list', process.env.DRIVER_ADD_MIDRUN + '\\n');
  got.dispose();
  console.log('IDENTITY ' + got.identity);
} catch (err) { console.log('ERROR ' + err.message); process.exitCode = 1; } })();
`);

let failures = 0;
/** Run one named case, count a failure instead of aborting the rest. */
function test(name, fn) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (err) {
    failures += 1;
    console.log(`FAIL ${name}\n     ${err.message}`);
  }
}
const read = (f) => (fs.existsSync(path.join(state, f)) ? fs.readFileSync(path.join(state, f), 'utf8') : '');
const calls = () => read('calls.jsonl').split('\n').filter(Boolean).map((l) => JSON.parse(l));
const finalList = () => read('list').split('\n').filter(Boolean);
const name = (c) => (c.argv[0] === '-i' ? c.cmds[0][0] : c.argv[0]);

function runImport(password, extra = {}) {
  fs.rmSync(state, { recursive: true, force: true });
  fs.mkdirSync(state);
  fs.writeFileSync(path.join(state, 'list'), LOGIN + '\n');
  return spawnSync(process.execPath, [DRIVER], {
    encoding: 'utf8',
    env: {
      ...process.env,
      PATH: `${bin}:${process.env.PATH}`,
      FAKE_STATE: state,
      FAKE_SHA: SHA,
      FAKE_TEMP_KC_RE: 'signing\\.keychain-db$',
      CSC_LINK: P12,
      CSC_KEY_PASSWORD: password,
      ...extra,
    },
  });
}

const HOSTILE = 'p"w\\ x \'y\' $z ;lock-keychain "q';
const PLAIN = 'Plain-p12-pw-5521';

test('no password string appears in any recorded argv or output', () => {
  const r = runImport(HOSTILE);
  assert.match(r.stdout, /IDENTITY B+/, r.stdout + r.stderr);
  const pwTokens = calls().flatMap((c) => c.cmds).filter((t) => t[0] === 'unlock-keychain');
  assert.equal(pwTokens.length, 1, 'one unlock-keychain on stdin');
  const keychainPw = pwTokens[0][pwTokens[0].indexOf('-p') + 1];
  assert.match(keychainPw, /^[0-9a-f]{48}$/);
  const argvText = calls().map((c) => c.argv.join(' ')).join('\n');
  for (const secret of [HOSTILE, keychainPw]) {
    assert.equal(argvText.includes(secret), false, 'a password reached an argv');
    assert.equal((r.stdout + r.stderr).includes(secret), false, 'a password reached an output');
  }
  assert.equal(read('violations.log'), '');
});

test('the password-carrying commands arrive on stdin of security -i', () => {
  runImport(PLAIN);
  const viaStdin = calls().filter((c) => c.argv[0] === '-i').map(name);
  for (const cmd of ['create-keychain', 'unlock-keychain', 'import', 'set-key-partition-list']) {
    assert.ok(viaStdin.includes(cmd), cmd + ' must be fed over stdin');
  }
  const direct = calls().filter((c) => c.argv[0] !== '-i').map(name);
  for (const cmd of ['create-keychain', 'unlock-keychain', 'import', 'set-key-partition-list']) {
    assert.equal(direct.includes(cmd), false, cmd + ' must not run with argv');
  }
  assert.ok(calls().some((c) => c.argv[0] === '-i' && c.cmds[0][0] === 'import' && c.cmds[0].includes(PLAIN)));
});

test('a password with quotes, a backslash and spaces round-trips and cannot start a second command', () => {
  const r = runImport(HOSTILE);
  assert.match(r.stdout, /IDENTITY/, r.stdout + r.stderr);
  const imp = calls().find((c) => c.argv[0] === '-i' && c.cmds[0][0] === 'import');
  assert.equal(imp.cmds.length, 1, 'exactly one command per security -i');
  assert.equal(imp.stdin.split('\n').filter(Boolean).length, 1, 'exactly one line on stdin');
  const t = imp.cmds[0];
  assert.equal(t[t.indexOf('-P') + 1], HOSTILE, 'the password parses back to itself');
  assert.equal(t.length, 10, 'no token was split or appended: ' + JSON.stringify(t.map((x) => (x === HOSTILE ? '<pw>' : x))));
});

test('a password with a newline, a carriage return or a NUL is refused before any security call', () => {
  for (const bad of ['a\nlock-keychain x', 'a\rb']) {
    const r = runImport(bad);
    assert.notEqual(r.status, 0);
    assert.match(r.stdout, /ERROR .*CSC_KEY_PASSWORD/, r.stdout);
    assert.equal(calls().length, 0, 'security must not run: ' + JSON.stringify(calls().map(name)));
  }
});

test('a NUL in the password is refused before any security call (in process: an env var cannot carry a NUL)', () => {
  fs.rmSync(state, { recursive: true, force: true });
  fs.mkdirSync(state);
  const saved = { ...process.env };
  Object.assign(process.env, { PATH: `${bin}:${process.env.PATH}`, FAKE_STATE: state });
  try {
    const { importIdentityFromEnv } = createRequire(import.meta.url)(moduleUnderTest);
    assert.throws(() => importIdentityFromEnv({ CSC_LINK: P12, CSC_KEY_PASSWORD: 'a\0b' }), /CSC_KEY_PASSWORD.*NUL/);
  } finally {
    process.env.PATH = saved.PATH;
  }
  assert.equal(calls().length, 0, 'security must not run');
});

test('an empty p12 password is refused before any security call (security -i cannot carry an empty token)', () => {
  const r = runImport('');
  assert.notEqual(r.status, 0);
  assert.match(r.stdout, /ERROR .*CSC_KEY_PASSWORD/, r.stdout);
  assert.equal(calls().length, 0);
});

test('a password over the size cap is refused before any security call and never echoed', () => {
  const big = 'A'.repeat(5000);
  const r = runImport(big);
  assert.notEqual(r.status, 0);
  assert.match(r.stdout, /ERROR .*CSC_KEY_PASSWORD/, r.stdout.slice(0, 200));
  assert.equal((r.stdout + r.stderr).includes('AAAAAAAAAA'), false, 'the password leaked into the error');
  assert.equal(calls().length, 0, 'security must not run: ' + JSON.stringify(calls().map(name)));
  const justOver = runImport('A'.repeat(1025));
  assert.notEqual(justOver.status, 0);
  assert.equal(calls().length, 0);
});

test('a password at the size cap made wholly of escaped characters still imports as one line', () => {
  const edge = '"'.repeat(1024);
  const r = runImport(edge);
  assert.match(r.stdout, /IDENTITY/, r.stdout.slice(0, 200) + r.stderr);
  const imp = calls().find((c) => c.argv[0] === '-i' && c.cmds[0][0] === 'import');
  assert.ok(Buffer.byteLength(imp.stdin) <= 4095, 'the line fits what security -i reads whole');
  assert.equal(imp.cmds[0][imp.cmds[0].indexOf('-P') + 1], edge);
});

test('a command line over what security -i reads whole is refused before it is sent, naming the command not the value', () => {
  let long = tmp;
  for (let i = 0; i < 3; i += 1) long = path.join(long, '\\'.repeat(250));
  fs.mkdirSync(long, { recursive: true });
  const longP12 = path.join(long, 'dummy.p12');
  fs.copyFileSync(P12, longP12);
  const edge = '"'.repeat(1024);
  const r = runImport(edge, { TMPDIR: long, CSC_LINK: longP12 });
  assert.notEqual(r.status, 0);
  assert.match(r.stdout, /ERROR security import .*4095/, r.stdout.slice(0, 300));
  assert.equal(r.stdout.includes('""""""""'), false, 'the password leaked into the error');
  for (const c of calls()) {
    assert.ok(Buffer.byteLength(c.stdin) <= 4095, 'an over-long line reached security: ' + Buffer.byteLength(c.stdin));
  }
  assert.equal(calls().some((c) => name(c) === 'import'), false, 'the over-long import must not be sent');
  assert.deepEqual(finalList(), [LOGIN]);
});

test('the keychain joins the list only after the unlock', () => {
  runImport(PLAIN);
  const seq = calls().map(name);
  const unlock = seq.indexOf('unlock-keychain');
  const firstListWrite = calls().findIndex((c) => c.argv[0] === 'list-keychains' && c.argv.includes('-s'));
  assert.ok(unlock >= 0 && firstListWrite > unlock, 'unlock then list: ' + seq.join(','));
  assert.equal(seq.indexOf('create-keychain') < unlock, true);
});

test('restore removes only the temporary keychain from the then-current list, before the delete', () => {
  const r = runImport(PLAIN, { DRIVER_ADD_MIDRUN: ANOTHER });
  assert.match(r.stdout, /IDENTITY/, r.stdout + r.stderr);
  assert.deepEqual(finalList(), [LOGIN, ANOTHER], 'the keychain added mid-run survives, the temporary one is gone');
  const all = calls();
  const kc = read('keychain');
  const writes = all.map((c, i) => [c, i]).filter(([c]) => c.argv[0] === 'list-keychains' && c.argv.includes('-s'));
  const removal = writes[writes.length - 1];
  const del = all.findIndex((c) => name(c) === 'delete-keychain');
  assert.ok(removal[0].argv.includes(ANOTHER) && !removal[0].argv.includes(kc));
  assert.ok(del > removal[1], 'unlist before delete');
  assert.ok(all.slice(removal[1] - 1, removal[1]).some((c) => c.argv[0] === 'list-keychains' && !c.argv.includes('-s')), 'the list was re-read right before the removal');
  assert.equal(read('violations.log'), '');
});

test('a failing security command is reported by name, the list is restored and no secret leaks', () => {
  const r = runImport(HOSTILE, { FAKE_FAIL: 'import' });
  assert.notEqual(r.status, 0);
  assert.match(r.stdout, /ERROR .*import failed/, r.stdout);
  assert.equal((r.stdout + r.stderr).includes(HOSTILE), false, 'the password leaked into the error');
  assert.deepEqual(finalList(), [LOGIN], 'a failure after create must leave the list as it was');
  assert.ok(calls().some((c) => name(c) === 'delete-keychain'), 'the keychain is deleted');
  const failed = calls().find((c) => name(c) === 'import');
  assert.ok(failed, 'the failing command was attempted');
});

test('a failed unlock aborts before the keychain ever joins the list', () => {
  const r = runImport(PLAIN, { FAKE_FAIL: 'unlock-keychain' });
  assert.notEqual(r.status, 0);
  assert.equal(calls().some((c) => c.argv[0] === 'list-keychains' && c.argv.includes('-s')), false, 'never listed while locked');
  assert.equal(read('violations.log'), '');
});

test('the temporary keychain is set to never auto-lock: set-keychain-settings with no flags, through security -i', () => {
  const r = runImport(PLAIN);
  assert.match(r.stdout, /IDENTITY/, r.stdout + r.stderr);
  const all = calls();
  const set = all.findIndex((c) => name(c) === 'set-keychain-settings');
  assert.ok(set >= 0, 'population check: the setting was written');
  assert.equal(all[set].argv[0], '-i', 'through security -i, not as a bare argv command');
  assert.equal(all[set].cmds[0].length, 2, 'no flags: the command and the keychain path only');
  assert.equal(all.some((c) => c.argv.includes('-lut')), false, 'no timeout is ever set');
  assert.ok(set < all.findIndex((c) => name(c) === 'unlock-keychain'), 'the setting is written before the unlock, with the keychain still new');
});

function runSignalled(signal, extra = {}) {
  return runImport(PLAIN, { DRIVER_RAISE: signal, ...extra });
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGQUIT']) {
  test(`${signal} during the pack unlists, then deletes the temporary keychain, and the process still dies by ${signal}`, () => {
    const r = runSignalled(signal);
    assert.equal(r.signal, signal, 'the signal is re-raised after the cleanup: ' + r.stdout + r.stderr);
    assert.deepEqual(finalList(), [LOGIN], 'the temporary keychain is off the list');
    const all = calls();
    const kc = read('keychain');
    const removal = all.findIndex((c) => c.argv[0] === 'list-keychains' && c.argv.includes('-s') && !c.argv.includes(kc) && all.indexOf(c) > all.findIndex((x) => name(x) === 'import'));
    const del = all.findIndex((c) => name(c) === 'delete-keychain');
    assert.ok(removal >= 0 && del > removal, 'population check: unlist then delete');
    assert.equal(fs.existsSync(path.dirname(kc)), false, 'the temp directory is gone');
    assert.equal(read('violations.log'), '');
  });
}

test('a second signal while the first one is cleaning up is ignored: the cleanup finishes', () => {
  const r = runSignalled('SIGHUP', { FAKE_SIGNAL_ON_DELETE: 'SIGTERM' });
  assert.equal(r.signal, 'SIGHUP', 'the first signal is the one re-raised: ' + r.stdout + r.stderr);
  const kc = read('keychain');
  assert.ok(kc, 'population check: the import ran');
  assert.equal(fs.existsSync(path.dirname(kc)), false, 'the temp directory is gone despite the second signal');
  assert.deepEqual(finalList(), [LOGIN]);
});

fs.rmSync(tmp, { recursive: true, force: true });

if (failures > 0) {
  console.log(`${failures} failed`);
  process.exit(1);
}
console.log('all passed');
