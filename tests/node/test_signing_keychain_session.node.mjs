
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { spawnSync, execFileSync } from 'node:child_process';
import { mirror, registry, specOf, GOOD_MANIFEST, hardenedBinaryFile, FRAMEWORK_UNDER_OUT } from './lib/release_mirror.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
const importSh = path.join(repo, 'scripts', 'signing', 'import-developer-id.sh');
const neverSh = path.join(repo, 'scripts', 'signing', 'set-signing-keychain-never-autolock.sh');
const helperSh = path.join(repo, 'macOS', 'scripts', 'signing-keychain-session.sh');

const PASSWORD = 'Zx9-fake-keychain-pw-7731';
const NYEDIS = 'A'.repeat(40);
const OTHER = '89A226D28EA3A887349AA98E13F8E25072C7A8AD';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'signing-session-'));
const bin = path.join(tmp, 'bin');
const home = path.join(tmp, 'userhome');
const keychains = path.join(home, 'Library', 'Keychains');
const SIGN = path.join(keychains, 'carnivore-signing.keychain-db');
const LOGIN = path.join(keychains, 'login.keychain-db');
const OTHER_KC = path.join(tmp, 'someone-else.keychain-db');
const state = path.join(tmp, 'state');
fs.mkdirSync(bin);
fs.mkdirSync(keychains, { recursive: true });
for (const f of [SIGN, LOGIN, OTHER_KC]) fs.writeFileSync(f, '');
const tree = mirror(repo, tmp);
const releaseSh = tree.releaseSh;
const registryFile = registry(tmp, String(specOf(tree.pkg, 'electron')));
const builtBinary = hardenedBinaryFile(tmp);

const PRELUDE = String.raw`#!/usr/bin/env node
const fs = require('fs');
const S = process.env.FAKE_STATE, SIGN = process.env.FAKE_SIGN_KC;
const rd = (f, d = '') => { try { return fs.readFileSync(S + '/' + f, 'utf8'); } catch { return d; } };
const wr = (f, v) => fs.writeFileSync(S + '/' + f, v);
const ap = (f, v) => fs.appendFileSync(S + '/' + f, v + '\n');
const locked = () => rd('locked', '1').trim() === '1';
const list = () => rd('list').split('\n').filter(Boolean);
const log = (m) => ap('calls.log', m);
const bad = (m) => ap('violations.log', m);
const invariant = (what) => { if (locked() && list().includes(SIGN)) bad('signing keychain on the list while locked, after: ' + what); };
const touch = (kc, what) => { if (kc === SIGN && locked()) bad('touched while locked: ' + what); };
`;

const SECURITY = PRELUDE + String.raw`
function exec(argv, via) {
  const cmd = argv[0], a = argv.slice(1);
  const shown = via === 'i' ? a.map((x, i) => (['-p', '-P', '-k'].includes(a[i - 1]) ? '***' : x)) : a;
  log('security' + (via === 'i' ? '-i ' : ' ') + cmd + ' ' + shown.join(' '));
  const last = a[a.length - 1];
  switch (cmd) {
    case 'list-keychains': {
      const s = a.indexOf('-s');
      if (s < 0 && process.env.FAKE_SECOND_SIGNAL && rd('npm.env') && !rd('second.sent')) {
        // The first signal already ended the build and the close is reading the list: send the second one now.
        wr('second.sent', '1');
        process.kill(Number(rd('script.pid')), 'SIGTERM');
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 700);
      }
      if (s < 0) { for (const p of list()) console.log('    "' + p + '"'); return 0; }
      const n = Number(rd('setcount', '0')) + 1; wr('setcount', String(n));
      if (process.env.FAKE_LIST_SET_FAIL_FROM && n >= Number(process.env.FAKE_LIST_SET_FAIL_FROM)) { console.error('fake: list-keychains -s failed'); return 1; }
      wr('list', a.slice(s + 1).join('\n') + '\n'); invariant('list-keychains -s'); return 0;
    }
    case 'unlock-keychain': {
      const pw = a[a.indexOf('-p') + 1];
      if (pw !== process.env.FAKE_PASSWORD) { console.error('security: SecKeychainUnlock: The user name or passphrase you entered is not correct.'); return 51; }
      wr('locked', '0'); invariant('unlock'); return 0;
    }
    case 'lock-keychain':
      // The pass lock must still exist at this moment: it is released only after the keychain is locked.
      wr('lockdir.at.lock', String(fs.existsSync(require('path').join(require('path').dirname(SIGN), 'carnivore-signing.pass.lock'))));
      wr('locked', '1'); invariant('lock-keychain');
      if (process.env.FAKE_RELIST_AFTER_LOCK && !rd('relisted')) { wr('relisted', '1'); ap('list', SIGN); } // something lists it again
      return 0;
    case 'find-identity': {
      const kc = last.endsWith('.keychain-db') ? last : null;
      if (kc) touch(kc, 'find-identity'); else invariant('find-identity over the search list');
      const mode = process.env.FAKE_IDENTITIES || 'both';
      console.log('  1) ' + process.env.FAKE_OTHER_SHA + ' "Developer ID Application: Alex Callen (MDH8UQ6H46)"');
      if (mode === 'both') console.log('  2) ' + process.env.FAKE_NYEDIS_SHA + ' "Developer ID Application: Nyedis (ARD6KN4BX4)"');
      return 0;
    }
    case 'import': touch(a[a.indexOf('-k') + 1], 'import'); wr('imported', '1'); return 0;
    case 'set-key-partition-list': touch(last, 'set-key-partition-list'); return 0;
    case 'dump-keychain':
      touch(last, 'dump-keychain');
      if (process.env.FAKE_KLBL) console.log('keychain: "k"\nclass: 0x00000010 \nattributes:\n    0x00000001 <blob>="Carnivore Developer ID Nyedis ARD6KN4BX4"\n    0x00000006 <blob>=0x' + process.env.FAKE_KLBL + '  "x"');
      return 0;
    case 'show-keychain-info':
      touch(last, 'show-keychain-info');
      console.error('Keychain "' + last + '" ' + (process.env.FAKE_KC_INFO || rd('kcinfo', 'no-timeout').trim()));
      return 0;
    case 'set-keychain-settings':
      // Only the never-auto-lock command may write a setting, and only unlocked, with no flags.
      if (!process.env.FAKE_ALLOW_SETTINGS) { bad('keychain settings written'); return 0; }
      touch(last, 'set-keychain-settings');
      if (a.length !== 1) bad('set-keychain-settings with flags: ' + a.join(' '));
      if (via !== 'i') bad('set-keychain-settings not sent through security -i');
      if (!process.env.FAKE_SETTINGS_NOOP) wr('kcinfo', 'no-timeout');
      return 0;
    case 'default-keychain': case 'login-keychain': bad(cmd + ' written'); return 0;
    default: return 0;
  }
}
const tok = (line) => (line.match(/"[^"]*"|\S+/g) || []).map((t) => t.replace(/^"|"$/g, ''));
const argv = process.argv.slice(2);
if (argv[0] === '-i') {
  let rc = 0;
  for (const line of fs.readFileSync(0, 'utf8').split('\n')) { if (line.trim()) { const r = exec(tok(line), 'i'); if (r) rc = r; } }
  process.exit(rc);
}
process.exit(exec(argv, 'argv'));
`;

const CODESIGN = PRELUDE + String.raw`
const argv = process.argv.slice(2);
log('codesign ' + argv.join(' '));
const k = argv.indexOf('--keychain');
const kc = k >= 0 ? argv[k + 1] : null;
if (kc) touch(kc, 'codesign');
if (!argv.includes('--sign')) process.exit(0);
if (kc === SIGN && !list().includes(SIGN)) { console.error(argv[argv.indexOf('--sign') + 1] + ': no identity found'); process.exit(1); }
if (process.env.FAKE_MIDRUN_ADD && !list().includes(process.env.FAKE_MIDRUN_ADD)) ap('list', process.env.FAKE_MIDRUN_ADD);
process.exit(process.env.FAKE_CODESIGN_FAIL ? 1 : 0);
`;

const AWS = PRELUDE + String.raw`
const argv = process.argv.slice(2).join(' ');
log('aws ' + argv.replace(/--secret-id \S+/, '--secret-id <id>'));
if (argv.includes('describe-secret')) { if (argv.includes('DeletedDate')) console.log('None'); process.exit(0); }
if (argv.includes('macos-signing-keychain')) console.log(process.env.FAKE_PASSWORD);
else if (argv.includes('asc-api-key')) console.log('{"key_id":"K1","issuer_id":"I1","p8":"p8data"}');
else if (argv.includes('developer-id-key')) process.stdout.write(fs.readFileSync(process.env.FAKE_BACKUP_KEY));
`;

const NPM = PRELUDE + String.raw`
const argv = process.argv.slice(2);
// The Electron policy asks the registry and then reads the manifest the build wrote (macOS/scripts/electron-policy.js).
if (argv[0] === 'view') { process.stdout.write(fs.readFileSync(process.env.FAKE_REGISTRY)); process.exit(0); }
log('npm ' + argv.join(' '));
const out = (argv.map((x) => (x.match(/^-c\.directories\.output=(.*)$/) || [])[1]).find(Boolean)) || 'dist';
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(out + '/latest-mac.yml', process.env.FAKE_MANIFEST);
// The re-stamp step (macOS/scripts/restamp-manifest.js) refuses a manifest naming a file that was never built: build each one.
for (const m of process.env.FAKE_MANIFEST.matchAll(/url:\s*(\S+)/g)) fs.writeFileSync(out + '/' + m[1], 'fake artifact ' + m[1]);
// The Electron fuse read (macOS/scripts/electron-fuses-check.js) looks at the built framework: a hardened fake.
fs.mkdirSync(require('path').dirname(out + '/${FRAMEWORK_UNDER_OUT}'), { recursive: true });
fs.copyFileSync(process.env.FAKE_BUILT_BINARY, out + '/${FRAMEWORK_UNDER_OUT}');
wr('script.pid', String(process.ppid));
ap('npm.ident', JSON.stringify(Object.keys(process.env).filter((k) => /SIGN_IDENTITY$/.test(k))));
ap('npm.env', 'CSC_KEYCHAIN=' + (process.env.CSC_KEYCHAIN || '') + ' listed=' + list().includes(SIGN) + ' locked=' + locked() + (process.env.FAKE_NPM_LOCKCHECK ? ' lock=' + rd('../userhome/Library/Keychains/carnivore-signing.pass.lock/owner').split('\n').slice(0, 2).join(' ') : ''));
if (process.env.FAKE_CONCURRENT) {
  // A second signing pass starts while this one is mid-build: run it to the end, bracketed in the call log.
  log('CONC-START');
  const c = require('child_process').spawnSync(process.env.FAKE_CONCURRENT, JSON.parse(process.env.FAKE_CONCURRENT_ARGS || '[]'), { encoding: 'utf8', env: { ...process.env, FAKE_ALLOW_SETTINGS: '1', FAKE_CONCURRENT: '' } });
  log('CONC-END');
  wr('conc.status', String(c.status)); wr('conc.stderr', c.stderr + c.stdout);
  wr('conc.after', 'listed=' + list().includes(SIGN) + ' locked=' + locked());
}
if (process.env.FAKE_NPM_SIGNAL) { process.kill(process.ppid, process.env.FAKE_NPM_SIGNAL === '1' ? 'SIGTERM' : process.env.FAKE_NPM_SIGNAL); const t = Date.now(); while (Date.now() - t < 400); process.exit(0); }
const id = argv.map((x) => (x.match(/^-c\.mac\.identity=(.*)$/) || [])[1]).find(Boolean);
if (id) {
  const r = require('child_process').spawnSync('codesign', ['--force', '--keychain', process.env.CSC_KEYCHAIN, '--sign', id, '/x'], { stdio: 'inherit' });
  process.exit(r.status);
}
process.exit(0);
`;

for (const [name, src] of Object.entries({ security: SECURITY, codesign: CODESIGN, aws: AWS, npm: NPM })) {
  fs.writeFileSync(path.join(bin, name), src, { mode: 0o755 });
}

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

function resetState({ list = [LOGIN], locked = true, info = 'no-timeout' } = {}) {
  fs.rmSync(state, { recursive: true, force: true });
  fs.mkdirSync(state);
  fs.writeFileSync(path.join(state, 'list'), list.join('\n') + '\n');
  fs.writeFileSync(path.join(state, 'locked'), locked ? '1' : '0');
  fs.writeFileSync(path.join(state, 'kcinfo'), info);
}
const read = (f) => (fs.existsSync(path.join(state, f)) ? fs.readFileSync(path.join(state, f), 'utf8') : '');
const calls = () => read('calls.log').split('\n').filter(Boolean);
const finalList = () => read('list').split('\n').filter(Boolean);
const isLocked = () => read('locked').trim() === '1';
const idx = (re, from = 0) => calls().findIndex((c, i) => i >= from && re.test(c));
const listWrites = () => calls().map((c, i) => [c, i]).filter(([c]) => /^security list-keychains -d user -s /.test(c));

function run(script, args, env = {}) {
  return spawnSync(script, args, {
    encoding: 'utf8',
    env: {
      ...process.env,
      HOME: home,
      PATH: `${bin}:${process.env.PATH}`,
      FAKE_STATE: state,
      FAKE_SIGN_KC: SIGN,
      FAKE_PASSWORD: PASSWORD,
      FAKE_NYEDIS_SHA: NYEDIS,
      FAKE_OTHER_SHA: OTHER,
      FAKE_REGISTRY: registryFile,
      FAKE_MANIFEST: GOOD_MANIFEST,
      FAKE_BUILT_BINARY: builtBinary,
      ...env,
    },
  });
}

function assertClean(r) {
  assert.equal(read('violations.log'), '', 'the fake recorded a violation');
  const everything = calls().filter((c) => !c.startsWith('security-i ')).join('\n') + r.stdout + r.stderr;
  assert.equal(everything.includes(PASSWORD), false, 'the keychain password reached an argv or an output');
}

const LOCK = path.join(keychains, 'carnivore-signing.pass.lock');


test('release-build: unlock, then list, sign, then unlist, then lock; list restored; no violation', () => {
  resetState();
  const r = run(releaseSh, []);
  assert.equal(r.status, 0, r.stderr);
  const unlock = idx(/^security-i unlock-keychain /);
  const add = listWrites().find(([c]) => c.includes(SIGN));
  const sign = idx(/^codesign .*--sign /);
  assert.ok(unlock >= 0 && add && sign >= 0, 'population check: unlock, list add and sign were all recorded');
  const remove = listWrites().find(([c, i]) => i > add[1] && !c.includes(SIGN));
  const lock = idx(/^security lock-keychain /);
  assert.ok(remove, 'a list write without the signing keychain follows the add');
  assert.ok(unlock < add[1], 'unlock comes before the list add');
  assert.ok(add[1] < sign && sign < remove[1], 'the identity is signed while listed');
  assert.ok(remove[1] < lock, 'unlist comes before lock');
  assert.ok(idx(/^security find-identity/) > unlock, 'no find-identity before the unlock');
  const info = idx(/^security show-keychain-info /);
  assert.ok(unlock < info && info < add[1], 'the auto-lock setting is read after the unlock and before the list add');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.ok(add[0].endsWith(`${LOGIN} ${SIGN}`), 'appended after the login keychain');
  assert.equal(isLocked(), true);
  assert.match(read('npm.env'), new RegExp(`CSC_KEYCHAIN=${SIGN} listed=true locked=false`));
  assert.match(calls().find((c) => c.startsWith('npm ')), new RegExp(`-c\\.mac\\.identity=${NYEDIS} `), 'identity reaches electron-builder by SHA-1, not the other team\'s');
  assert.equal(calls().some((c) => c.includes(OTHER)), false, 'the other team\'s identity is never used');
  assertClean(r);
});

test('release-build: a failing codesign still restores the list and locks', () => {
  resetState();
  const r = run(releaseSh, [], { FAKE_CODESIGN_FAIL: '1' });
  assert.notEqual(r.status, 0);
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assert.ok(idx(/^security lock-keychain /) > idx(/^security list-keychains -d user -s [^]*$/, idx(/^codesign/)));
  assertClean(r);
});

test('release-build: a keychain someone else adds mid-run survives', () => {
  resetState();
  const r = run(releaseSh, [], { FAKE_MIDRUN_ADD: OTHER_KC });
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(finalList(), [LOGIN, OTHER_KC]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('release-build: a SIGTERM in the middle of the signing pass restores the list and locks', () => {
  resetState();
  const r = run(releaseSh, [], { FAKE_NPM_SIGNAL: '1' });
  assert.notEqual(r.status, 0);
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('release-build: a SIGQUIT (Ctrl-backslash) in the middle of the signing pass restores the list, locks, and releases the pass lock', () => {
  fs.rmSync(LOCK, { recursive: true, force: true });
  resetState();
  const r = run(releaseSh, [], { FAKE_NPM_SIGNAL: 'SIGQUIT' });
  assert.notEqual(r.status, 0);
  assert.equal(read('npm.env') !== '', true, 'population check: the signal was sent mid-build');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assert.equal(fs.existsSync(LOCK), false, 'the pass lock is released');
  assertClean(r);
});

test('release-build: a keychain that auto-locks is refused before the list is ever written, and the owner command is named', () => {
  for (const info of ['lock-on-sleep timeout=3600s', 'timeout=3600s', 'lock-on-sleep no-timeout']) {
    resetState();
    const r = run(releaseSh, [], { FAKE_KC_INFO: info });
    assert.notEqual(r.status, 0, info);
    assert.equal(listWrites().length, 0, `the search list was never written (${info})`);
    assert.deepEqual(finalList(), [LOGIN]);
    assert.equal(isLocked(), true);
    assert.equal(idx(/^npm /), -1, 'the build never ran');
    assert.ok(idx(/^security show-keychain-info /) > idx(/^security-i unlock-keychain /) && idx(/^security show-keychain-info /) >= 0, 'population check: the setting was read, after the unlock');
    assert.match(r.stderr, /scripts\/signing\/set-signing-keychain-never-autolock\.sh/, 'the documented never-auto-lock command is named');
    assert.doesNotMatch(r.stderr, /run: security set-keychain-settings/, 'the bare command that pops the password box is not offered');
    assertClean(r);
  }
});

test('release-build: a second signal during the close does not cut it short; the list is restored and the keychain locked', () => {
  resetState();
  const r = run(releaseSh, [], { FAKE_NPM_SIGNAL: '1', FAKE_SECOND_SIGNAL: '1' });
  assert.notEqual(r.status, 0);
  assert.equal(read('second.sent'), '1', 'population check: the second signal was sent during the close');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('release-build: an unlock that fails never lists the keychain', () => {
  resetState();
  fs.writeFileSync(path.join(bin, 'aws'), AWS.replace("console.log(process.env.FAKE_PASSWORD)", "console.log('not-the-password')"), { mode: 0o755 });
  try {
    const r = run(releaseSh, []);
    assert.notEqual(r.status, 0);
    assert.equal(listWrites().length, 0, 'the search list was never written');
    assert.deepEqual(finalList(), [LOGIN]);
    assert.equal(isLocked(), true);
    assert.equal(idx(/^npm /), -1, 'the build never ran');
    assertClean(r);
  } finally {
    fs.writeFileSync(path.join(bin, 'aws'), AWS, { mode: 0o755 });
  }
});

test('release-build: already on the list at start (a crashed earlier run), it is said so, left out of the add, then unlisted before the lock', () => {
  resetState({ list: [LOGIN, SIGN] });
  const r = run(releaseSh, []);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, /already on the search list/, 'the stale listing is named on stderr');
  const writes = listWrites();
  assert.equal(writes.length, 1, 'one list write: the removal; nothing was appended again');
  assert.equal(writes[0][0].includes(SIGN), false, 'the write leaves the signing keychain off');
  const lock = idx(/^security lock-keychain /);
  assert.ok(lock > writes[0][1], 'unlist comes before lock');
  assert.ok(idx(/^npm /) >= 0 && idx(/^npm /) < writes[0][1], 'population check: the build ran while it was listed');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('release-build: an already-listed keychain that auto-locks is refused, then unlisted and locked', () => {
  resetState({ list: [LOGIN, SIGN], info: 'lock-on-sleep timeout=3600s' });
  const r = run(releaseSh, []);
  assert.notEqual(r.status, 0);
  assert.equal(idx(/^npm /), -1, 'the build never ran');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('release-build: inherited identity overrides never reach the build', () => {
  resetState();
  const r = run(releaseSh, [], { CLOUDE_SIGN_IDENTITY: 'Evil', CARNIVORE_SIGN_IDENTITY: 'Evil', CLOUDECODE_SIGN_IDENTITY: 'Evil' });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(read('npm.ident').trim(), '[]', 'population check: the build ran and saw no *_SIGN_IDENTITY variable');
  assertClean(r);
});

test('release-build: a password over 1024 bytes, or with a CR or newline, is refused with zero security calls and no value in the error', () => {
  for (const pw of ['p'.repeat(1025), 'ab\rcd', 'ab\ncd']) {
    resetState();
    const r = run(releaseSh, [], { FAKE_PASSWORD: pw });
    assert.notEqual(r.status, 0, JSON.stringify(pw.slice(0, 8)));
    assert.deepEqual(calls().filter((c) => /^security/.test(c)), [], 'no security call at all');
    assert.equal(idx(/^npm /), -1, 'the build never ran');
    assert.equal((r.stdout + r.stderr).includes(pw.slice(0, 8)), false, 'the value is not in the error');
    assert.match(r.stderr, /longer than 1024 bytes|newline, carriage return or NUL/);
  }
  resetState();
  const ok = run(releaseSh, [], { FAKE_PASSWORD: 'p'.repeat(1024) });
  assert.equal(ok.status, 0, 'population check: exactly 1024 bytes is accepted: ' + ok.stderr);
});

test('helper: a security -i command line over 4095 bytes (newline included) is refused before security runs, naming the command not the value', () => {
  resetState();
  const secret = 'S3cretTail';
  const r = spawnSync('bash', ['-c', `die() { echo "$*" >&2; exit 1; }; source "${helperSh}"; kcs_security_i unlock-keychain "unlock-keychain -p \"$LONG\" x"`], {
    encoding: 'utf8',
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, FAKE_STATE: state, FAKE_SIGN_KC: SIGN, LONG: 'a'.repeat(4100) + secret },
  });
  assert.equal(r.status, 1);
  assert.deepEqual(calls(), [], 'security never ran');
  assert.match(r.stderr, /unlock-keychain command line exceeds the 4095-byte line/);
  assert.equal(r.stderr.includes(secret), false);
  resetState();
  const okLine = 'unlock-keychain -p "' + 'a'.repeat(4071) + '" x';
  assert.equal(Buffer.byteLength(okLine) + 1, 4095, 'population check: the boundary line is exactly at the limit');
  const r2 = spawnSync('bash', ['-c', `die() { echo "$*" >&2; exit 1; }; source "${helperSh}"; kcs_security_i unlock-keychain "$LINE"`], {
    encoding: 'utf8',
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, FAKE_STATE: state, FAKE_SIGN_KC: SIGN, FAKE_PASSWORD: PASSWORD, LINE: okLine },
  });
  assert.equal(r2.stderr.includes('exceeds'), false, r2.stderr);
  assert.equal(calls().length, 1, 'the boundary line reached security -i');
});

test('release-build: if the keychain cannot be taken off the list it is not locked', () => {
  resetState();
  const r = run(releaseSh, [], { FAKE_LIST_SET_FAIL_FROM: '2' });
  assert.notEqual(r.status, 0, 'a build that could not clean up is not a success');
  assert.deepEqual(finalList(), [LOGIN, SIGN]);
  assert.equal(isLocked(), false);
  assert.equal(read('violations.log'), '', 'listed but never locked while listed');
  assert.equal(fs.existsSync(LOCK), true, 'a run that could not unlist keeps its pass lock');
  fs.rmSync(LOCK, { recursive: true, force: true });
});

test('release-build: a keychain that reappears on the list after the lock is taken off again, said so, and the run fails', () => {
  fs.rmSync(LOCK, { recursive: true, force: true });
  resetState();
  const r = run(releaseSh, [], { FAKE_RELIST_AFTER_LOCK: '1' });
  assert.notEqual(r.status, 0, 'a close that found it relisted is not a success');
  assert.match(r.stderr, /reappeared on the search list/);
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assert.equal(read('relisted'), '1', 'population check: the fake relisted it');
  assert.equal(fs.existsSync(LOCK), false);
  assertClean(r);
});

test('release-build: the pass lock still exists at the moment lock-keychain runs', () => {
  fs.rmSync(LOCK, { recursive: true, force: true });
  resetState();
  const r = run(releaseSh, []);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(read('lockdir.at.lock'), 'true');
  assert.equal(fs.existsSync(LOCK), false, 'and it is gone afterwards');
});


test('release-build: an argument naming identity, keychain, cscLink, notarize, forceCodeSigning, a config file or -c.mac.* is refused before any call', () => {
  const bad = [['-c.mac.identity=-'], ['-c.mac.notarize=false'], ['-c.forceCodeSigning=false'], ['--config.mac.identity=x'], ['-c.mac.hardenedRuntime=false'],
    ['--config', 'evil.yml'], ['-c', 'evil.yml'], ['--config=evil.yml'], ['-c.CSC_LINK=x'], ['-c.cscKeyPassword=x'], ['-c.mac.keychain=x'], ['--mac.identity=x'], ['-c.afterSign.notarize=1']];
  for (const args of bad) {
    resetState();
    const r = run(releaseSh, args);
    assert.notEqual(r.status, 0, args.join(' '));
    assert.match(r.stderr, /refusing the build argument/, args.join(' '));
    assert.deepEqual(calls(), [], `no aws, security or npm call (${args.join(' ')})`);
  }
});

test('release-build: update_proof.py\'s exact arguments still pass through after the forced settings', () => {
  for (const extra of [[], ['-c.extraMetadata.version=1.2.3']]) {
    resetState();
    const dir = path.join(tmp, 'identity-keychain-out');
    const r = run(releaseSh, [`-c.directories.output=${dir}`, '--publish', 'never', ...extra]);
    assert.equal(r.status, 0, r.stderr);
    const npm = calls().find((c) => c.startsWith('npm '));
    assert.ok(npm.includes(`-c.mac.identity=${NYEDIS} -c.forceCodeSigning=true -c.directories.output=${dir} --publish never`), npm);
    if (extra.length) assert.ok(npm.endsWith(extra[0]), npm);
    assertClean(r);
  }
});

test('release-build: ad hoc plan builds without the keychain on the list and with no CSC_KEYCHAIN', () => {
  resetState();
  const r = run(releaseSh, [], { FAKE_IDENTITIES: 'other' });
  assert.equal(r.status, 0, r.stderr);
  assert.match(read('npm.env'), /CSC_KEYCHAIN= listed=false locked=true/);
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('release-build and import-developer-id share one implementation: neither touches the list, lock or settings itself', () => {
  for (const f of [releaseSh, importSh, neverSh]) {
    const src = fs.readFileSync(f, 'utf8').split('\n').filter((l) => !l.trim().startsWith('#')).join('\n');
    assert.doesNotMatch(src, /list-keychains|lock-keychain|set-keychain-settings|default-keychain/, f);
    assert.match(src, /signing-keychain-session\.sh/, `${f} sources the shared helper`);
    assert.match(src, /cleanup\(\) \{\n  local rc=\$\?\n  trap '' INT TERM HUP QUIT/, `${f} ignores further signals while the EXIT trap closes the keychain`);
    assert.match(src, /trap 'exit 130' INT TERM HUP QUIT\n/, `${f} turns INT TERM HUP QUIT into an exit (an untrapped SIGQUIT skips the EXIT trap)`);
  }
});


test('never-autolock: unlock, then set-keychain-settings with no flags through security -i, then verify, then lock; no password on argv', () => {
  resetState({ info: 'lock-on-sleep timeout=3600s' });
  const r = run(neverSh, [], { FAKE_ALLOW_SETTINGS: '1' });
  assert.equal(r.status, 0, r.stderr);
  const unlock = idx(/^security-i unlock-keychain /);
  const set = idx(/^security-i set-keychain-settings /);
  const info = idx(/^security show-keychain-info /);
  const lock = idx(/^security lock-keychain /);
  assert.ok(unlock >= 0 && set >= 0 && info >= 0 && lock >= 0, 'population check: every step ran: ' + calls().join(' | '));
  assert.ok(unlock < set && set < info && info < lock, 'unlock, set, verify, lock');
  assert.equal(calls()[set], `security-i set-keychain-settings ${SIGN}`, 'no flags');
  assert.equal(read('kcinfo'), 'no-timeout');
  assert.equal(listWrites().length, 0, 'the search list is never written');
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('never-autolock: a keychain that still reports an auto-lock after the command fails the run, and is still locked', () => {
  resetState({ info: 'lock-on-sleep timeout=3600s' });
  const r = run(neverSh, [], { FAKE_ALLOW_SETTINGS: '1', FAKE_SETTINGS_NOOP: '1' });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /still reports an auto-lock/);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('never-autolock: a keychain left on the list by a crashed run is unlisted before the lock', () => {
  resetState({ list: [LOGIN, SIGN], info: 'timeout=3600s' });
  const r = run(neverSh, [], { FAKE_ALLOW_SETTINGS: '1' });
  assert.equal(r.status, 0, r.stderr);
  const writes = listWrites();
  assert.equal(writes.length, 1);
  assert.ok(writes[0][1] < idx(/^security lock-keychain /), 'unlist before lock');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('never-autolock: a refused password makes no security call and writes no setting', () => {
  resetState({ info: 'timeout=3600s' });
  const r = run(neverSh, [], { FAKE_ALLOW_SETTINGS: '1', FAKE_PASSWORD: 'p'.repeat(1025) });
  assert.notEqual(r.status, 0);
  assert.deepEqual(calls().filter((c) => /^security/.test(c)), []);
  assert.equal(read('kcinfo'), 'timeout=3600s');
});


test('adhoc-sign: a plain package and a release pass never run security', () => {
  resetState();
  const script = `
    const hook = require(${JSON.stringify(path.join(repo, 'macOS', 'scripts', 'adhoc-sign.js'))});
    const fs = require('fs'), path = require('path');
    if (hook.chooseIdentity() !== null) throw new Error('a plain package must pick no identity');
    const out = ${JSON.stringify(path.join(tmp, 'app-out'))};
    fs.mkdirSync(path.join(out, 'Carnivore.app'), { recursive: true });
    const ctx = { electronPlatformName: 'darwin', appOutDir: out,
      packager: { appInfo: { productFilename: 'Carnivore' }, platformSpecificBuildOptions: { identity: ${JSON.stringify(NYEDIS)} } } };
    Promise.resolve(hook(ctx)).catch((e) => { console.error(e.message); process.exit(1); });`;
  const env = { PATH: `${bin}:${process.env.PATH}`, HOME: home, FAKE_STATE: state, FAKE_SIGN_KC: SIGN, CSC_KEYCHAIN: SIGN };
  const r = spawnSync('node', ['-e', script], { encoding: 'utf8', env });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /skipped: electron-builder signs/, 'population check: the release branch ran');
  assert.deepEqual(calls(), [], 'neither path ran security or codesign');
});


test('adhoc-sign: an identity of team MDH8UQ6H46 is refused whatever CLOUDE_SIGN_IDENTITY names, by SHA-1, full name or part; another identity still works', () => {
  const choose = (value) => {
    resetState();
    const script = `try { console.log('CHOSE ' + require(${JSON.stringify(path.join(repo, 'macOS', 'scripts', 'adhoc-sign.js'))}).chooseIdentity()); } catch (e) { console.log('THREW ' + e.message); }`;
    const env = { PATH: `${bin}:${process.env.PATH}`, HOME: home, FAKE_STATE: state, FAKE_SIGN_KC: SIGN, FAKE_NYEDIS_SHA: NYEDIS, FAKE_OTHER_SHA: OTHER, CLOUDE_SIGN_IDENTITY: value };
    return spawnSync('node', ['-e', script], { encoding: 'utf8', env }).stdout;
  };
  assert.match(choose(NYEDIS), new RegExp(`^CHOSE ${NYEDIS}`), 'population check: a normal identity is chosen');
  for (const value of [OTHER, 'Developer ID Application: Alex Callen (MDH8UQ6H46)', 'Alex Callen', 'Anyone (MDH8UQ6H46)']) {
    assert.match(choose(value), /^THREW .*MDH8UQ6H46/, value);
  }
});

test('adhoc-sign: the afterPack hook inside a release pass is not refused, even with the forbidden identity in the environment', () => {
  resetState();
  const script = `
    const hook = require(${JSON.stringify(path.join(repo, 'macOS', 'scripts', 'adhoc-sign.js'))});
    const fs = require('fs'), path = require('path');
    const out = ${JSON.stringify(path.join(tmp, 'app-out2'))};
    fs.mkdirSync(path.join(out, 'Carnivore.app'), { recursive: true });
    const ctx = { electronPlatformName: 'darwin', appOutDir: out,
      packager: { appInfo: { productFilename: 'Carnivore' }, platformSpecificBuildOptions: { identity: ${JSON.stringify(NYEDIS)} } } };
    Promise.resolve(hook(ctx)).catch((e) => { console.error(e.message); process.exit(1); });`;
  const env = { PATH: `${bin}:${process.env.PATH}`, HOME: home, FAKE_STATE: state, FAKE_SIGN_KC: SIGN, CSC_KEYCHAIN: SIGN, CLOUDE_SIGN_IDENTITY: 'Developer ID Application: Alex Callen (MDH8UQ6H46)' };
  const r = spawnSync('node', ['-e', script], { encoding: 'utf8', env });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /skipped: electron-builder signs/);
  assert.deepEqual(calls(), [], 'no security or codesign call');
});


function makeKeyAndCert() {
  const key = path.join(tmp, 'devid.key');
  const cert = path.join(tmp, 'devid.pem');
  execFileSync('openssl', ['genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', key], { stdio: 'ignore' });
  execFileSync('openssl', ['req', '-new', '-x509', '-key', key, '-out', cert, '-days', '2', '-subj', '/CN=Developer ID Application: Nyedis (ARD6KN4BX4)/OU=ARD6KN4BX4'], { stdio: 'ignore' });
  const klbl = execFileSync('bash', ['-c', `openssl pkey -in "${key}" -pubout -outform DER | openssl dgst -sha1 -r | cut -d' ' -f1 | tr a-f A-F`], { encoding: 'utf8' }).trim();
  return { key, cert, klbl };
}
const material = makeKeyAndCert();
function keyCopy(name) {
  const k = path.join(tmp, name);
  fs.copyFileSync(material.key, k);
  fs.chmodSync(k, 0o600);
  return k;
}
const importEnv = (k, extra = {}) => ({ CARNIVORE_DEVID_KEY: k, FAKE_BACKUP_KEY: material.key, FAKE_KLBL: material.klbl, ...extra });

test('import-developer-id: the codesign proof runs with the keychain unlocked and listed, then it is unlisted and locked', () => {
  resetState();
  const k = keyCopy('imp1.key');
  const r = run(importSh, [material.cert], importEnv(k));
  assert.equal(r.status, 0, r.stderr);
  const unlock = idx(/^security-i unlock-keychain /);
  const add = listWrites().find(([c]) => c.includes(SIGN));
  const sign = idx(/^codesign .*--sign /);
  assert.ok(unlock >= 0 && add && sign >= 0, 'population check');
  const remove = listWrites().find(([c, i]) => i > add[1] && !c.includes(SIGN));
  const lock = idx(/^security lock-keychain /);
  assert.ok(unlock < add[1] && add[1] < sign && sign < remove[1] && remove[1] < lock, 'unlock, list, sign, unlist, lock');
  for (const re of [/^security dump-keychain/, /^security find-identity/, /^security-i set-key-partition-list/]) {
    assert.ok(idx(re) > unlock, `${re} comes after the unlock`);
  }
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assert.equal(fs.existsSync(k), false, 'key file deleted after codesign proved it signs');
  assertClean(r);
});

test('import-developer-id: a failing codesign keeps the key file and still restores the list and locks', () => {
  resetState();
  const k = keyCopy('imp2.key');
  const r = run(importSh, [material.cert], importEnv(k, { FAKE_CODESIGN_FAIL: '1' }));
  assert.notEqual(r.status, 0);
  assert.ok(fs.existsSync(k), 'key file must be kept');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assertClean(r);
});

test('import-developer-id: a keychain that auto-locks is refused before the list is written, and the key file is kept', () => {
  resetState();
  const k = keyCopy('imp3.key');
  const r = run(importSh, [material.cert], importEnv(k, { FAKE_KC_INFO: 'lock-on-sleep timeout=3600s' }));
  assert.notEqual(r.status, 0);
  assert.equal(listWrites().length, 0, 'the search list was never written');
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assert.ok(fs.existsSync(k), 'key file must be kept');
  assertClean(r);
});


function plantLock(pid, start) {
  fs.mkdirSync(LOCK);
  const startLine = start === null ? '' : `start=${start ?? spawnSync('ps', ['-o', 'lstart=', '-p', String(pid)], { encoding: 'utf8' }).stdout.trim()}\n`;
  fs.writeFileSync(path.join(LOCK, 'owner'), `pid=${pid}\n${startLine}ts=2026-10-07T00:00:00Z\nowner=test\n`);
}
function deadPid() {
  return 999999;
}

test('lock: each other signing script started during a release-build pass is refused with no security call, and the running pass keeps the keychain', () => {
  for (const other of [neverSh, importSh, releaseSh]) {
    fs.rmSync(LOCK, { recursive: true, force: true });
    resetState();
    const k = keyCopy('conc.key');
    const r = run(releaseSh, [], importEnv(k, { FAKE_CONCURRENT: other, FAKE_CONCURRENT_ARGS: JSON.stringify(other === importSh ? [material.cert] : []) }));
    assert.equal(r.status, 0, r.stderr);
    assert.notEqual(read('conc.status'), '0', `${path.basename(other)} must be refused`);
    assert.match(read('conc.stderr'), /another signing pass is running \(pid \d+ holds .*carnivore-signing\.pass\.lock\)/, path.basename(other));
    assert.doesNotMatch(read('conc.stderr'), new RegExp(PASSWORD));
    const all = calls();
    const a = all.indexOf('CONC-START'), b = all.indexOf('CONC-END');
    assert.ok(a >= 0 && b > a, 'population check: the second pass ran inside the first');
    assert.deepEqual(all.slice(a + 1, b).filter((c) => /^(security|codesign|npm)/.test(c)), [], `the refused pass made no security, codesign or npm call (${path.basename(other)})`);
    assert.equal(read('conc.after'), 'listed=true locked=false', 'the running pass still has the keychain listed and unlocked');
    assert.equal(read('violations.log'), '');
    assert.equal(fs.existsSync(LOCK), false, 'the first pass released its lock at the end');
    assert.deepEqual(finalList(), [LOGIN]);
    assert.equal(isLocked(), true);
  }
});

test('lock: held during the pass, released after the keychain is locked', () => {
  fs.rmSync(LOCK, { recursive: true, force: true });
  resetState();
  const r = run(releaseSh, [], { FAKE_NPM_LOCKCHECK: '1' });
  assert.equal(r.status, 0, r.stderr);
  assert.match(read('npm.env'), /lock=pid=\d+/, 'population check: the lock held the pass pid while the build ran');
  assert.equal(fs.existsSync(LOCK), false);
  assertClean(r);
});

test('lock: a live owner is refused before anything runs, and its lock is left alone', () => {
  resetState();
  fs.rmSync(LOCK, { recursive: true, force: true });
  plantLock(process.pid);
  try {
    for (const script of [neverSh, importSh, releaseSh]) {
      const r = run(script, script === importSh ? [material.cert] : [], importEnv(keyCopy('live.key'), { FAKE_ALLOW_SETTINGS: '1' }));
      assert.notEqual(r.status, 0, path.basename(script));
      assert.match(r.stderr, new RegExp(`another signing pass is running \\(pid ${process.pid} holds `));
      assert.deepEqual(calls().filter((c) => /^(security|codesign|npm)/.test(c)), [], 'no security, codesign or npm call was made');
      assert.ok(fs.existsSync(path.join(LOCK, 'owner')), 'the live owner\'s lock is untouched');
      assert.equal(isLocked(), true);
    }
  } finally {
    fs.rmSync(LOCK, { recursive: true, force: true });
  }
});

test('lock: a dead owner\'s lock is reported and broken, the keychain it left listed is cleaned, and the lock is released', () => {
  resetState({ list: [LOGIN, SIGN] });
  fs.rmSync(LOCK, { recursive: true, force: true });
  const dead = deadPid();
  plantLock(dead);
  const r = run(releaseSh, []);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, new RegExp(`belongs to pid ${dead}, which is gone; breaking it`));
  assert.match(r.stderr, /already on the search list/);
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(isLocked(), true);
  assert.equal(fs.existsSync(LOCK), false);
  assert.deepEqual(fs.readdirSync(keychains).filter((f) => f.includes('.broken.')), [], 'the broken lock was cleaned up');
  assertClean(r);
});

test('lock: a live pid whose start time differs (a reused pid) is a dead owner; one with the same start time is live', () => {
  resetState({ list: [LOGIN, SIGN] });
  fs.rmSync(LOCK, { recursive: true, force: true });
  plantLock(process.pid, 'Mon Jan  1 00:00:00 2001');
  const r = run(releaseSh, []);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, new RegExp(`names pid ${process.pid}, now another process`));
  assert.deepEqual(finalList(), [LOGIN]);
  assert.equal(fs.existsSync(LOCK), false);
  assert.equal(spawnSync('ps', ['-o', 'lstart=', '-p', String(process.pid)], { encoding: 'utf8' }).stdout.trim().length > 0, true, 'population check: ps reports a start time');
  assertClean(r);
  fs.rmSync(LOCK, { recursive: true, force: true });
  resetState();
  const r2 = run(releaseSh, [], { FAKE_NPM_LOCKCHECK: '1' });
  assert.equal(r2.status, 0, r2.stderr);
  assert.match(read('npm.env'), /lock=pid=\d+ start=\S+/, 'the owner file carries the pass start time');
});

test('lock: a refused password releases the lock it took', () => {
  resetState();
  fs.rmSync(LOCK, { recursive: true, force: true });
  const r = run(releaseSh, [], { FAKE_PASSWORD: 'p'.repeat(1025) });
  assert.notEqual(r.status, 0);
  assert.equal(fs.existsSync(LOCK), false, 'the lock does not outlive the run');
  assert.deepEqual(calls().filter((c) => /^security/.test(c)), []);
});

fs.rmSync(tmp, { recursive: true, force: true });

if (failures > 0) {
  console.log(`${failures} failed`);
  process.exit(1);
}
console.log('all passed');
