import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { TrayApiClient } = require(path.join(here, '..', '..', 'macOS', 'tray-api.js'));

function rig(code, failures) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(init.method);
    if (calls.length <= failures) throw new TypeError('fetch failed', { cause: { code } });
    return { ok: true, status: 201, json: async () => ({ name: 'x' }) };
  };
  return { calls, client: new TrayApiClient({ baseUrl: 'http://127.0.0.1:1', getOtp: () => null, fetchImpl }) };
}

test('a POST reset on a stale socket is retried once and lands', async () => {
  const { client, calls } = rig('ECONNRESET', 1);
  const answer = await client.request('/api/v1/projects', { method: 'POST', body: { name: 'x' }, token: 't' });
  assert.equal(answer.ok, true);
  assert.deepEqual(calls, ['POST', 'POST']);
});

test('a second reset is reported, not looped; other failures are never retried', async () => {
  const twice = rig('ECONNRESET', 2);
  assert.equal((await twice.client.request('/p', { method: 'POST', body: {}, token: 't' })).ok, false);
  assert.equal(twice.calls.length, 2);
  const refused = rig('ECONNREFUSED', 1);
  assert.equal((await refused.client.request('/p', { method: 'POST', body: {}, token: 't' })).ok, false);
  assert.equal(refused.calls.length, 1);
});
