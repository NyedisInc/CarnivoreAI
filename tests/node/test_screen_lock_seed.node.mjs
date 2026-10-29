import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { createScreenLock, parseConsoleLock } = require(path.join(here, '..', '..', 'macOS', 'screen-lock.js'));

const user = (uid, locked) => `<dict>
<key>CGSSessionUniqueSessionUUID</key><string>AAAA</string>
${locked === undefined ? '' : `<key>CGSSessionScreenIsLocked</key>\n<${locked}/>`}
<key>kCGSSessionOnConsoleKey</key><true/>
<key>kCGSSessionUserIDKey</key>
<integer>${uid}</integer>
</dict>`;
const plist = (...dicts) => `<?xml version="1.0"?><plist><dict>
<key>IOConsoleUsers</key><array>${dicts.join('')}</array>
<key>IOKitBuildVersion</key><string>x</string></dict></plist>`;

function rig(answer) {
  const handlers = {};
  const monitor = { on: (name, fn) => { handlers[name] = fn; } };
  let release;
  const gate = new Promise((r) => { release = r; });
  const calls = [];
  const exec = (file, args, options, cb) => {
    calls.push({ file, args, options });
    gate.then(() => (answer instanceof Error ? cb(answer, '') : cb(null, answer)));
  };
  const logs = [];
  const lock = createScreenLock(monitor, { platform: 'darwin', exec, uid: 502, log: (l) => logs.push(l) });
  return { lock, handlers, release, calls, logs };
}

test('locked before the read resolves; the call is fixed and absolute', async () => {
  const r = rig(plist(user(502, 'true')));
  assert.equal(r.lock.isLocked(), true);
  r.release(); await r.lock.seeded;
  assert.equal(r.calls.length, 1);
  assert.equal(r.calls[0].file, '/usr/sbin/ioreg');
  assert.deepEqual(r.calls[0].args, ['-n', 'Root', '-d1', '-a']);
  assert.equal(r.calls[0].options.timeout, 2000);
});

test('the OS says locked: locked; the OS says unlocked (flag false or absent): unlocked', async () => {
  for (const [dict, want, word] of [[user(502, 'true'), true, 'locked'], [user(502, 'false'), false, 'unlocked'], [user(502), false, 'unlocked']]) {
    const r = rig(plist(dict)); r.release(); await r.lock.seeded;
    assert.equal(r.lock.isLocked(), want);
    assert.equal(r.logs.length, 1);
    assert.match(r.logs[0], new RegExp(`OS flag says ${word}`));
  }
});

test('a failed read stays locked until the first unlock-screen event', async () => {
  for (const answer of [new Error('ENOENT'), 'not a plist', plist(user(999, 'false'))]) {
    const r = rig(answer); r.release(); await r.lock.seeded;
    assert.equal(r.lock.isLocked(), true);
    assert.match(r.logs[0], /read failed; assuming locked/);
    r.handlers['unlock-screen']();
    assert.equal(r.lock.isLocked(), false);
  }
});

test('an unlock-screen event before the read resolves wins over a late locked read', async () => {
  const r = rig(plist(user(502, 'true')));
  r.handlers['unlock-screen']();
  assert.equal(r.lock.isLocked(), false);
  r.release(); await r.lock.seeded;
  assert.equal(r.lock.isLocked(), false);
  assert.match(r.logs[0], /event wins/);
});

test('a lock-screen event before the read resolves wins over a late unlocked read', async () => {
  const r = rig(plist(user(502, 'false')));
  r.handlers['lock-screen']();
  r.release(); await r.lock.seeded;
  assert.equal(r.lock.isLocked(), true);
});

test('a plist with two console users picks our uid', () => {
  const xml = plist(user(501, 'true'), user(502, 'false'));
  assert.equal(parseConsoleLock(xml, 502), false);
  assert.equal(parseConsoleLock(xml, 501), true);
  assert.equal(parseConsoleLock(xml, 7), null);
  assert.equal(parseConsoleLock('', 502), null);
});

test('off darwin nothing is read and the tracker starts unlocked', () => {
  let called = false;
  const lock = createScreenLock({ on: () => {} }, { platform: 'linux', exec: () => { called = true; } });
  assert.equal(lock.isLocked(), false);
  assert.equal(called, false);
  assert.equal(createScreenLock(null, { platform: 'darwin' }).isLocked(), false);
});

test('a shape the parser does not fully understand reads as no answer (null, tracker stays locked), never unlocked', () => {
  const nested = `<dict>
<key>CGSSessionUniqueSessionUUID</key><string>AAAA</string>
<key>kCGSSessionUserIDKey</key><integer>502</integer>
<key>extra</key><dict><key>a</key><string>b</string></dict>
<key>CGSSessionScreenIsLocked</key><true/>
</dict>`;
  assert.equal(parseConsoleLock(plist(nested), 502), null, 'uid, then a nested dict, then a true flag (the old parser read this as unlocked)');
  const asInt = user(502, 'true').replace('<true/>\n<key>kCGSSessionOnConsoleKey', '<integer>1</integer>\n<key>kCGSSessionOnConsoleKey');
  assert.ok(asInt.includes('<integer>1</integer>'));
  assert.equal(parseConsoleLock(plist(asInt), 502), null, 'flag as an integer');
  assert.equal(parseConsoleLock(plist(user(502, 'true'), user(502, 'false')), 502), null, 'two entries for our uid that disagree');
  assert.equal(parseConsoleLock(plist(user(502, 'true'), user(502, 'true')), 502), true, 'agreeing duplicates are fine');
  assert.equal(parseConsoleLock(plist(user(502, 'false')).replace('</array>', ''), 502), null, 'unbalanced tags');
  const withArray = user(502, 'false').replace('<key>kCGSSessionOnConsoleKey', '<key>list</key><array><string>x</string></array><key>kCGSSessionOnConsoleKey');
  assert.equal(parseConsoleLock(plist(withArray), 502), null, 'array inside the entry');
});
