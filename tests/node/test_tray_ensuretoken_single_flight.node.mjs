import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { TrayApiClient } = require(path.join(here, '..', '..', 'macOS', 'tray-api.js'));

function makeClient({ failVerify = false } = {}) {
  const calls = { verify: 0, refresh: 0 };
  const fetchImpl = async (url) => {
    const route = new URL(url).pathname;
    await new Promise((resolve) => setTimeout(resolve, 10));
    if (route.endsWith('/auth/verify')) {
      calls.verify += 1;
      if (failVerify) return { ok: false, status: 429, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => ({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }) };
    }
    calls.refresh += 1;
    return { ok: true, status: 200, json: async () => ({ access_token: 'b', expires_in: 3600 }) };
  };
  const client = new TrayApiClient({ baseUrl: 'http://127.0.0.1:1', getOtp: () => '000000', fetchImpl });
  return { client, calls };
}

test('five concurrent ensureToken calls make one verify request', async () => {
  const { client, calls } = makeClient();
  const results = await Promise.all(Array.from({ length: 5 }, () => client.ensureToken()));
  assert.equal(calls.verify, 1);
  for (const r of results) assert.deepEqual(r, { token: 'a', error: null });
});

test('five concurrent calls with a refresh token make one refresh request', async () => {
  const { client, calls } = makeClient();
  client.refreshToken = 'r0';
  await Promise.all(Array.from({ length: 5 }, () => client.ensureToken()));
  assert.equal(calls.refresh, 1);
  assert.equal(calls.verify, 0);
});

test('a failed exchange is not cached: the next call tries again', async () => {
  const { client, calls } = makeClient({ failVerify: true });
  const burst = await Promise.all([client.ensureToken(), client.ensureToken()]);
  assert.equal(calls.verify, 1);
  for (const r of burst) assert.equal(r.token, null);
  assert.equal(client.tokenFlight, null);
  await client.ensureToken();
  assert.equal(calls.verify, 2);
});
