// WHY THIS FILE EXISTS
//     }

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.join(here, '..', 'macOS');
const managerSrc = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
const mainSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'actions', 'server.js'), 'utf8');

const { decideLifecycleAction } = require(path.join(macDir, 'ownership-policy.js'));

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

console.log('adopted-server refusals: visible, and honest about what is running');


test('THE FALSE CLAIM: refusing to restart a LIVE adopted server must not report it stopped', () => {
  const d = decideLifecycleAction({
    action: 'restart',
    owned: false,
    serverResponding: true,
  });
  assert.equal(d.permitted, false, 'we killed a server we did not start');
  assert.notEqual(
    d.stateAfterRefusal,
    'stopped',
    'the refusal reported the server as STOPPED while it was still serving ' +
    'every request. The tray reads this state, so the menu bar lies about a ' +
    'running server.'
  );
  assert.equal(d.stateAfterRefusal, 'running');
});

test('a refusal about a server that is NOT responding may say stopped', () => {
  const d = decideLifecycleAction({
    action: 'restart',
    owned: false,
    serverResponding: false,
  });
  assert.equal(d.permitted, false);
  assert.equal(d.stateAfterRefusal, 'stopped');
});

test('a refusal that could not MEASURE the server changes no state at all', () => {
  for (const unknown of [undefined, null, 'maybe']) {
    const d = decideLifecycleAction({
      action: 'restart',
      owned: false,
      serverResponding: unknown,
    });
    assert.equal(d.permitted, false);
    assert.equal(
      d.stateAfterRefusal,
      null,
      `serverResponding=${JSON.stringify(unknown)} produced a state verdict ` +
      'that nothing measured. null means leave the state alone.'
    );
  }
});


test('a refusal carries a reason and an offer, not just a false return', () => {
  const d = decideLifecycleAction({
    action: 'restart',
    owned: false,
    serverResponding: true,
  });
  assert.equal(typeof d.reason, 'string');
  assert.ok(
    d.reason.length > 30,
    'the refusal reason is too thin to show anyone, which is how this became ' +
    'a console.log nobody read'
  );
  assert.equal(
    d.offerTakeOwnership,
    true,
    'the user is refused and offered nothing, so Restart on an adopted server ' +
    'is a permanent dead end - and an adopted server is the one most likely ' +
    'to need restarting'
  );
});

test('Stop on an adopted server refuses the same way', () => {
  const d = decideLifecycleAction({
    action: 'stop',
    owned: false,
    serverResponding: true,
  });
  assert.equal(d.permitted, false);
  assert.equal(d.stateAfterRefusal, 'running');
  assert.equal(d.offerTakeOwnership, true);
});


test('explicit consent permits it - the guard is a default, not a wall', () => {
  for (const action of ['stop', 'restart']) {
    const d = decideLifecycleAction({
      action,
      owned: false,
      serverResponding: true,
      takeOwnership: true,
    });
    assert.equal(
      d.permitted,
      true,
      `${action} was refused even though the user explicitly took ownership`
    );
  }
});

test('consent is never assumed from anything other than an explicit true', () => {
  for (const sloppy of ['yes', 1, {}, [], 'false']) {
    const d = decideLifecycleAction({
      action: 'stop',
      owned: false,
      serverResponding: true,
      takeOwnership: sloppy,
    });
    assert.equal(
      d.permitted,
      false,
      `${JSON.stringify(sloppy)} was accepted as consent to kill a process ` +
      'this app did not start'
    );
  }
});


test('an OWNED server is permitted without any prompting', () => {
  for (const action of ['stop', 'restart']) {
    const d = decideLifecycleAction({ action, owned: true, serverResponding: true });
    assert.equal(d.permitted, true, `${action} on our own server was refused`);
    assert.equal(d.offerTakeOwnership, false);
  }
});

test('an unknown action is refused rather than defaulting to permitted', () => {
  const d = decideLifecycleAction({ action: 'obliterate', owned: true });
  assert.equal(d.permitted, false);
});

// --- wiring (SOURCE-LEVEL) ------------------------------------------------

test('wiring (SOURCE-LEVEL): the old unconditional state=stopped is gone from the refusal', () => {
  const at = managerSrc.indexOf('async stop(');
  assert.notEqual(at, -1, 'stop() is gone');
  const body = managerSrc.slice(at, at + 5000);
  const adoptedAt = body.indexOf('ownedProcess');
  assert.notEqual(adoptedAt, -1, 'stop() no longer distinguishes adopted from owned');
  const branch = body.slice(adoptedAt, adoptedAt + 1200);
  const code = branch
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  assert.ok(
    !/this\.state\s*=\s*'stopped'/.test(code),
    "the adopted branch still hardcodes state = 'stopped' about a server it " +
    'just admitted is still running'
  );
});

test('wiring (SOURCE-LEVEL): restart() reports its refusal instead of returning silently', () => {
  const at = managerSrc.indexOf('async restart(');
  assert.notEqual(at, -1, 'restart() is gone');
  const body = managerSrc.slice(at, at + 2500);
  assert.ok(
    /decideLifecycleAction\(|refus/i.test(body),
    'restart() still delegates entirely to stop() and cannot tell the caller ' +
    'that nothing happened, which is why the menu item looked broken'
  );
  assert.ok(
    /return\s*\{/.test(body),
    'restart() returns nothing, so the menu has no way to know it refused'
  );
});

test('wiring (SOURCE-LEVEL): the menu shows the refusal and offers the way out', () => {
  assert.ok(
    /result\.refused/.test(mainSrc),
    'the tray ignores what restart() returned, so a refusal is still a dead ' +
    'click from the user\'s point of view'
  );
  const at = mainSrc.indexOf("'server.restart'");
  assert.notEqual(at, -1, 'the Restart Server action is gone');
  const region = mainSrc.slice(at, at + 1200);
  assert.ok(
    /showMessageBox|showErrorBox/.test(region),
    'clicking Restart on an adopted server still produces no visible result'
  );
});

console.log(`\nadopted-server refusals: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASS');
