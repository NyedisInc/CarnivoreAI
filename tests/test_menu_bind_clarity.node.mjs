// WHY THIS FILE EXISTS

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const macDir = path.join(repoRoot, 'macOS');

const trayStatus = require(path.join(macDir, 'tray-status.js'));

let passed = 0;
const failures = [];
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log('  ok   ' + name);
  } catch (err) {
    failures.push(name);
    console.log('  FAIL ' + name + '\n       ' + err.message);
  }
}

const ANY_ADDRESS = /\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/;

console.log('bind row');

test('a measured bind matching configuration is stated plainly', () => {
  const row = trayStatus.describeBind({
    effectiveHost: '0.0.0.0',
    configuredHost: '0.0.0.0',
  });
  assert.equal(row.known, true);
  assert.equal(row.applied, true);
  assert.match(row.label, /0\.0\.0\.0/);
});

test('an UNKNOWN bind puts no address in the row at all', () => {
  const row = trayStatus.describeBind({
    effectiveHost: null,
    configuredHost: '0.0.0.0',
  });
  assert.equal(row.known, false);
  assert.ok(
    !ANY_ADDRESS.test(row.label),
    'the row displayed an address while the effective bind was unknown: ' +
      JSON.stringify(row.label)
  );
  assert.ok(
    !row.label.includes('0.0.0.0'),
    'the configured value reached the row: ' + JSON.stringify(row.label)
  );
});

test('an unknown bind says it is unknown rather than leaving a blank', () => {
  const row = trayStatus.describeBind({
    effectiveHost: null,
    configuredHost: '192.168.1.50',
  });
  assert.match(row.label, /unknown|not measured/i);
  assert.match(row.detail, /192\.168\.1\.50/);
  assert.match(row.detail, /configur/i);
});

test('an empty string is unknown, not an address', () => {
  const row = trayStatus.describeBind({
    effectiveHost: '',
    configuredHost: '0.0.0.0',
  });
  assert.equal(row.known, false);
  assert.ok(!ANY_ADDRESS.test(row.label));
});

test('a bind that differs from configuration names the restart', () => {
  const row = trayStatus.describeBind({
    effectiveHost: '127.0.0.1',
    configuredHost: '0.0.0.0',
  });
  assert.equal(row.known, true);
  assert.equal(row.applied, false);
  assert.match(row.label, /127\.0\.0\.1/);
  assert.match(row.label, /restart/i);
  assert.ok(
    row.label.indexOf('127.0.0.1') < row.label.indexOf('0.0.0.0'),
    'the configured address is stated before the one in force, which is the ' +
      'reading order that caused the confusion in the first place'
  );
});

console.log('');
console.log('setup row');

const { setupLabel, setupHint } = require(path.join(macDir, 'tray-menu', 'model', 'server.js'));
const { t: catalogT } = await import('./node/tray_menu_fixtures.mjs');
const setupRow = (setup) => {
  const snap = { setup, joined: false };
  const hint = setupHint(snap, catalogT);
  return `${setupLabel(snap, catalogT)} ${hint ? hint.sublabel : ''}`.trim();
};

test('an unfinished setup names the action, not just the status', () => {
  const label = setupRow('incomplete');
  assert.match(label, /setup/i);
  assert.match(label, /open|finish/i);
  assert.match(label, /restart/i);
});

test('an undetermined setup does not claim to be incomplete', () => {
  const label = setupRow('undetermined');
  assert.match(label, /unknown|could not/i);
  assert.ok(
    !/not finished|finish setup/i.test(label),
    '"could not determine" was rendered as a definite verdict'
  );
});

test('a finished setup is an ordinary row with no alarm words', () => {
  const label = setupRow('complete');
  assert.ok(!/not finished|unknown/i.test(label), label);
  assert.match(label, /setup/i);
});

test('an unpolled setup is not rendered as finished', () => {
  assert.notEqual(setupRow(null), setupRow('complete'));
});

console.log('');
console.log('menu construction (SOURCE-LEVEL over the tray menu model, macOS/tray-menu/, #1896)');

const phoneSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'model', 'phone.js'), 'utf8');
const snapshotSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'snapshot.js'), 'utf8');
const managerSrc = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');

test('the bind row is built from describeBind, not from getBindHost', () => {
  const fn = phoneSrc;
  assert.ok(fn.length > 200, 'could not read model/phone.js');
  assert.match(fn, /describeBind\(/);
  assert.ok(
    !/label:\s*`Bind IP:\s*\$\{bindHost\}`/.test(fn),
    'the row still prints the CONFIGURED bind host as though it were the ' +
      'address in force'
  );
});

test('the copy-URL row is built from the MEASURED bind only', () => {
  assert.match(snapshotSrc, /measuredUrl:\s*sm\.getMeasuredUrl\(\)/);
  const fn = phoneSrc;
  assert.match(fn, /const url = phone\.measuredUrl \|\| null;/);
  assert.ok(
    !/`Copy URL:\s*\$\{publishedUrl\}`/.test(fn),
    'Copy URL is built from the best-effort navigation URL, which falls ' +
      'back to configuration and can hand him a dead address to paste'
  );
});

test('getMeasuredUrl refuses to fall back to the configured host', () => {
  const marker = '\n  getMeasuredUrl() {';
  const start = managerSrc.indexOf(marker);
  assert.notEqual(start, -1, 'getMeasuredUrl is not defined as a method');
  const fn = managerSrc.slice(start, start + 900);
  assert.ok(
    !/getBindHost\(\)/.test(fn),
    'getMeasuredUrl reaches for configuration, which is the fallback the ' +
      'whole change removes'
  );
  assert.match(fn, /getEffectiveBindHost\(\)/);
});

console.log('');
console.log('menu-bind-clarity: ' + passed + ' passed, ' + failures.length + ' failed');
process.exit(failures.length > 0 ? 1 : 0);
