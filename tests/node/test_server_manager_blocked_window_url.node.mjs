import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');

function load() {
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? { app: { getPath: () => '/tmp', getVersion: () => '0.0.0', isPackaged: false } } : realLoad.call(this, request, ...rest); };
  try {
    return require(path.join(macDir, 'server-manager.js'));
  } finally {
    Module._load = realLoad;
  }
}

function fake(blocked) {
  return { startBlockedReason: blocked, getPort: () => 5051, getBindHost: () => '127.0.0.1', getEffectiveBindHost: () => '127.0.0.1', getPrimaryLanIp: () => null };
}

test('getAppWindowUrl: null while the start is refused, loopback url otherwise', () => {
  const SM = load();
  assert.equal(SM.prototype.getAppWindowUrl.call(fake('holder-other-user')), null);
  assert.match(SM.prototype.getAppWindowUrl.call(fake(null)), /^http:\/\/127\.0\.0\.1:5051/);
});
