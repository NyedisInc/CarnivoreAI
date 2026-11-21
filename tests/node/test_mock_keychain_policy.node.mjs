import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const policy = require('../../macOS/mock-keychain-policy.js');

const SELF_SIGNED = 'Executable=/A/Carnivore.app/Contents/MacOS/Carnivore\nCodeDirectory v=20400 size=301\nTeamIdentifier=not set\n';
const DEV_ID = 'CodeDirectory v=20500 size=9\nAuthority=Developer ID Application: X (ABCDE12345)\nTeamIdentifier=ABCDE12345\n';
const EXE = '/A/Carnivore.app/Contents/MacOS/Carnivore';

test('no Team ID uses the mock keychain', () => {
  assert.equal(policy.shouldUseMockKeychain({ env: {}, report: SELF_SIGNED }), true);
});
test('a Team ID keeps the keychain', () => {
  assert.equal(policy.shouldUseMockKeychain({ env: {}, report: DEV_ID }), false);
});
test('an unreadable or unsigned report keeps the keychain', () => {
  assert.equal(policy.shouldUseMockKeychain({ env: {}, report: '' }), false);
  assert.equal(policy.shouldUseMockKeychain({ env: {}, report: '/A.app: code object is not signed at all' }), false);
});
test('override wins in both directions, canonical and legacy', () => {
  assert.equal(policy.shouldUseMockKeychain({ env: { CARNIVORE_MOCK_KEYCHAIN: '0' }, report: SELF_SIGNED }), false);
  assert.equal(policy.shouldUseMockKeychain({ env: { CLOUDE_MOCK_KEYCHAIN: 'on' }, report: DEV_ID }), true);
});
test('apply appends the switch only when decided, and skips codesign when overridden', () => {
  const seen = [];
  const app = { commandLine: { appendSwitch: (s) => seen.push(s) } };
  assert.equal(policy.applyMockKeychainPolicy(app, { env: {}, exePath: EXE, run: () => ({ stdout: '', stderr: SELF_SIGNED }) }), true);
  assert.deepEqual(seen, ['use-mock-keychain']);
  const boom = () => { throw new Error('codesign must not run'); };
  assert.equal(policy.applyMockKeychainPolicy(app, { env: { CARNIVORE_MOCK_KEYCHAIN: '0' }, exePath: EXE, run: boom }), false);
  assert.equal(seen.length, 1);
});
