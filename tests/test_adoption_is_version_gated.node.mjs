// WHY THIS FILE EXISTS

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.join(here, '..', 'macOS');
const managerSrc = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');

const {
  decideAdoption,
  ADOPT_MATCH,
  ADOPT_MISMATCH,
  ADOPT_RUNNING_UNKNOWN,
  ADOPT_BUNDLE_UNKNOWN,
} = require(path.join(macDir, 'adoption-decision.js'));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ok   ${name}`);
    passed += 1;
  } catch (err) {
    console.log(`  FAIL ${name}`);
    console.log(`       ${err.message}`);
    failed += 1;
  }
}

console.log('adoption: may this bundle adopt the server already on the port');


test('THE INCIDENT: a 1.0.2 server is NOT adopted by a 1.0.3 bundle', () => {
  const d = decideAdoption({ runningVersion: '1.0.2', bundleVersion: '1.0.3' });
  assert.equal(
    d.adopt,
    false,
    'the upgrade adopted the old version\'s server. This is the defect: four ' +
    'hours of v1.0.2 code running under a v1.0.3 bundle.'
  );
  assert.equal(d.outcome, ADOPT_MISMATCH);
  assert.match(d.reason, /1\.0\.2/);
  assert.match(d.reason, /1\.0\.3/);
});

test('a DOWNGRADE is refused too, not just an upgrade', () => {
  const d = decideAdoption({ runningVersion: '1.0.3', bundleVersion: '1.0.2' });
  assert.equal(d.adopt, false);
  assert.equal(d.outcome, ADOPT_MISMATCH);
});

test('a MATCHING version IS adopted - the crash-recovery case still works', () => {
  const d = decideAdoption({ runningVersion: '1.0.3', bundleVersion: '1.0.3' });
  assert.equal(
    d.adopt,
    true,
    'adoption was refused for a server running exactly this bundle\'s code. ' +
    'That breaks Electron crash recovery and would double-spawn onto a held ' +
    'port, or kill live sessions for no reason.'
  );
  assert.equal(d.outcome, ADOPT_MATCH);
});


test('a running server that does NOT report a version is NOT adopted', () => {
  for (const missing of [undefined, null, '', '   ']) {
    const d = decideAdoption({ runningVersion: missing, bundleVersion: '1.0.3' });
    assert.equal(
      d.adopt,
      false,
      `a server reporting ${JSON.stringify(missing)} as its version was ` +
      'adopted. "I could not tell" is not "yes".'
    );
    assert.equal(d.outcome, ADOPT_RUNNING_UNKNOWN);
  }
});

test('a bundle that cannot resolve its OWN version does not adopt either', () => {
  const d = decideAdoption({ runningVersion: '1.0.3', bundleVersion: '' });
  assert.equal(d.adopt, false);
  assert.equal(d.outcome, ADOPT_BUNDLE_UNKNOWN);
});

test('both unknown is still not a match', () => {
  const d = decideAdoption({ runningVersion: '', bundleVersion: '' });
  assert.equal(
    d.adopt,
    false,
    'two empty strings compared equal and were treated as a match, which is ' +
    'the single most likely way this gate gets accidentally disabled'
  );
});

test('every outcome carries a reason a human can act on', () => {
  const cases = [
    { runningVersion: '1.0.2', bundleVersion: '1.0.3' },
    { runningVersion: '1.0.3', bundleVersion: '1.0.3' },
    { runningVersion: '', bundleVersion: '1.0.3' },
    { runningVersion: '1.0.3', bundleVersion: '' },
  ];
  for (const c of cases) {
    const d = decideAdoption(c);
    assert.equal(typeof d.reason, 'string');
    assert.ok(d.reason.length > 20, `thin reason for ${JSON.stringify(c)}`);
  }
});


test('a leading v and surrounding whitespace do not fake a mismatch', () => {
  const d = decideAdoption({ runningVersion: ' v1.0.3 ', bundleVersion: '1.0.3' });
  assert.equal(d.adopt, true, 'v1.0.3 and 1.0.3 were treated as different');
  assert.equal(d.outcome, ADOPT_MATCH);
});

test('a non-string version is CANNOT DETERMINE, never coerced', () => {
  for (const junk of [1.03, {}, [], true, NaN]) {
    const d = decideAdoption({ runningVersion: junk, bundleVersion: '1.0.3' });
    assert.equal(d.adopt, false, `${JSON.stringify(junk)} was accepted`);
    assert.equal(d.outcome, ADOPT_RUNNING_UNKNOWN);
  }
});

test('a build suffix is a real difference, not noise', () => {
  const d = decideAdoption({
    runningVersion: '1.0.3-2-gabc1234',
    bundleVersion: '1.0.3',
  });
  assert.equal(d.adopt, false);
  assert.equal(d.outcome, ADOPT_MISMATCH);
});

test('decideAdoption called with nothing at all does not throw and does not adopt', () => {
  assert.equal(decideAdoption().adopt, false);
  assert.equal(decideAdoption({}).adopt, false);
});

// --- wiring (SOURCE-LEVEL) ------------------------------------------------

test('wiring (SOURCE-LEVEL): start() consults the gate before adopting', () => {
  assert.ok(
    /require\('\.\/adoption-decision'\)/.test(managerSrc),
    'server-manager does not import the adoption gate at all, so whatever it ' +
    'decides is untested'
  );
  const at = managerSrc.indexOf('async start(');
  assert.notEqual(at, -1, 'start() is gone');
  const body = managerSrc.slice(at, at + 8000);
  const adoptAt = body.indexOf('adopting it');
  const decideAt = body.indexOf('decideAdoption(');
  assert.notEqual(decideAt, -1, 'start() never calls decideAdoption');
  assert.ok(
    decideAt < adoptAt || adoptAt === -1,
    'start() adopts before it decides whether it may, which makes the gate ' +
    'decorative'
  );
});

test('wiring (SOURCE-LEVEL): the refusal is thrown, not logged and swallowed', () => {
  const at = managerSrc.indexOf('async start(');
  const body = managerSrc.slice(at, at + 8000);
  assert.ok(
    /ADOPTION_REFUSED/.test(body),
    'a refused adoption does not raise anything the menu can show, so the ' +
    'user sees a server that silently did not start'
  );
});

test('wiring (SOURCE-LEVEL): the post-start health resync cannot undo a refusal', () => {
  const mainSrc = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  const at = mainSrc.indexOf('Force immediate health check');
  assert.notEqual(at, -1, 'the post-start resync is gone; re-check this guard');
  const region = mainSrc.slice(at, at + 900);
  assert.ok(
    /startBlockedReason/.test(region),
    'the post-start health resync is not gated on the refusal, so a refused ' +
    'adoption is promoted straight back to "running"'
  );
});

test('wiring (SOURCE-LEVEL): a refusal reaches the user as a choice, not a dead end', () => {
  const mainSrc = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.ok(
    /ADOPTION_REFUSED/.test(mainSrc),
    'main.js does not distinguish a refused adoption from any other start ' +
    'failure, so the user is told something is wrong and nothing about what ' +
    'they can do'
  );
  assert.ok(
    /restartAdoptedEngine\(/.test(mainSrc),
    'there is no way for the user to restart the engine on this version, so the only ' +
    'remaining move is Activity Monitor'
  );
  const dialogs = fs.readFileSync(path.join(macDir, 'engine', 'engine-dialogs.js'), 'utf8');
  const at = dialogs.indexOf("t('desktop.engine_restart.restart'), t('desktop.engine_restart.quit')");
  assert.notEqual(at, -1, 'the restart prompt does not offer both options');
  assert.match(dialogs.slice(at, at + 120), /defaultId:\s*0/, 'restart is not the default button');
});

test('wiring (SOURCE-LEVEL): takeOverPort confirms the kill AND the port', () => {
  const at = managerSrc.indexOf('async takeOverPort(');
  assert.notEqual(at, -1, 'takeOverPort is gone');
  const body = managerSrc.slice(at, at + 2000);
  assert.ok(/terminateProcess\(/.test(body), 'the holder is not terminated');
  assert.ok(
    /result\.terminated/.test(body),
    'the kill result is never checked, so a failed kill falls through to a ' +
    'spawn that will fail on a held port with a confusing bind error'
  );
  assert.ok(
    /waitForPortFree\(/.test(body),
    'a dead pid is not a free port - a released socket lingers - and spawning ' +
    'into that window fails as something else entirely'
  );
});

test('holderRefusal: only a listener of this user passes; a stranger, no listener and a null read are refused', () => {
  const { holderRefusal } = require(path.join(macDir, 'tray-menu', 'port-trust.js'));
  const mine = { pid: 10, command: 'python3', uid: 501 };
  assert.equal(holderRefusal([mine], 501), null);
  assert.equal(holderRefusal([mine, { pid: 11, command: 'python3', uid: 502 }], 501).reason, 'not_yours');
  assert.equal(holderRefusal([{ pid: 11, command: 'nc', uid: 0 }], 501).reason, 'not_yours');
  assert.equal(holderRefusal([], 501).reason, 'unknown', 'a health answer with no listener of mine is foreign');
  assert.equal(holderRefusal(null, 501).reason, 'unknown');
  assert.equal(holderRefusal([{ pid: 12, command: 'x', uid: null }], 501).reason, 'not_yours', 'an unreadable owner is not mine');
});

test('wiring (SOURCE-LEVEL): start() checks the listener is this user\'s before the version gate, and refuses with its own code', () => {
  const at = managerSrc.indexOf('async start(');
  const body = managerSrc.slice(at, at + 10000);
  const holder = body.indexOf('portTrust.holderRefusal(');
  const gate = body.indexOf('decideAdoption({');
  assert.ok(holder > 0 && gate > holder, `holderRefusal at ${holder} must come before decideAdoption at ${gate}`);
  assert.ok(/throw portTrust\.holderError\(/.test(body.slice(holder, gate)), 'the refusal is thrown');
  const { holderError } = require(path.join(macDir, 'tray-menu', 'port-trust.js'));
  const err = holderError({ reason: 'not_yours', holder: { pid: 7, command: 'python3', uid: 502 } }, 8000);
  assert.equal(err.code, 'PORT_HOLDER_NOT_YOURS'); assert.match(err.message, /PID 7 \(python3, uid 502\)/);
  assert.match(holderError({ reason: 'unknown', holder: null }, 8000).message, /could not confirm it is yours/);
});

console.log(`\nadoption: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASS');
