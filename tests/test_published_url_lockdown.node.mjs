// WHY THIS FILE EXISTS

import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`  ok   ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`  FAIL ${name}`);
    console.log(`       ${err.message}`);
  }
}

const { resolvePublishedUrl } = require(path.join(repoRoot, 'macOS', 'published-url.js'));

function stub({ port = 8000, configured = '0.0.0.0', measured = null, lan = '10.0.1.5' }) {
  return { port, configuredHost: configured, measuredHost: measured, lanIp: lan };
}

console.log('getPublishedUrl under the setup lockdown');

test('UNMEASURED bind resolves to loopback, not a LAN address nothing may be listening on', () => {
  const url = resolvePublishedUrl(stub({ measured: null, configured: '0.0.0.0' }));
  assert.equal(
    url,
    'http://127.0.0.1:8000',
    `an unmeasured bind produced ${url}. During the setup lockdown - the ` +
    `state every fresh install is in - the server listens ONLY on loopback, ` +
    `so this URL is connection-refused and the menu item opens a browser ` +
    `error page on a healthy server.`
  );
});

test('MEASURED 0.0.0.0 still yields the LAN address, which is the point of measuring', () => {
  const url = resolvePublishedUrl(stub({ measured: '0.0.0.0', configured: '0.0.0.0' }));
  assert.equal(
    url,
    'http://10.0.1.5:8000',
    `a measured 0.0.0.0 bind produced ${url}; the LAN address is real here ` +
    `and is what the user shares with another device`
  );
});

test('MEASURED loopback (the lockdown, once reported) yields loopback', () => {
  const url = resolvePublishedUrl(stub({ measured: '127.0.0.1', configured: '0.0.0.0' }));
  assert.equal(url, 'http://127.0.0.1:8000');
});

test('a measured specific LAN bind is used verbatim', () => {
  const url = resolvePublishedUrl(stub({ measured: '192.168.1.250', configured: '192.168.1.250' }));
  assert.equal(url, 'http://192.168.1.250:8000');
});

test('no LAN interface plus a measured 0.0.0.0 still yields loopback', () => {
  const url = resolvePublishedUrl(stub({ measured: '0.0.0.0', lan: null }));
  assert.equal(url, 'http://127.0.0.1:8000');
});

test('an undeterminable port yields null rather than a guessed-port URL', () => {
  const s = stub({});
  s.port = null;
  assert.equal(resolvePublishedUrl(s), null);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
