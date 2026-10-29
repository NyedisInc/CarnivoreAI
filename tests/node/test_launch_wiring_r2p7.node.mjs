import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const macDir = path.join(root, 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));

test('startTrayMenu hands the tray menu electron.powerMonitor', () => {
  const src = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  const start = src.indexOf('function startTrayMenu()');
  assert.ok(start > 0, 'startTrayMenu not found');
  const literal = src.slice(start, src.indexOf('onListing:', start));
  assert.match(literal, /electron: \{[^}]*powerMonitor/, 'the electron object given to createTrayMenu has no powerMonitor');
});

test('the take-over dialog gets a client for the engine port when the tray has none', () => {
  const { createLaunchApi } = require(path.join(macDir, 'engine', 'launch-api.js'));
  class Fake { constructor(o) { Object.assign(this, o); } }
  const sm = { getLocalApiUrl: () => 'http://127.0.0.1:8000', getCurrentOtp: () => '123456' };
  const tray = { tray: true };
  assert.equal(createLaunchApi({ serverManager: sm, member: null, TrayApiClient: Fake, trayApi: () => tray })(), tray);
  const get = createLaunchApi({ serverManager: sm, member: { isJoined: () => false, tokens: async () => null }, TrayApiClient: Fake, trayApi: () => null });
  const api = get();
  assert.equal(api.baseUrl, 'http://127.0.0.1:8000');
  assert.equal(api.getOtp(), '123456');
  assert.equal(get(), api, 'one client is reused for the same port');
  assert.equal(createLaunchApi({ serverManager: { getLocalApiUrl: () => null }, member: null, TrayApiClient: Fake, trayApi: () => null })(), null);
});
