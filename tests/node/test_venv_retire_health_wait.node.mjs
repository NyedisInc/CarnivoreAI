import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const retire = require('../../macOS/engine/venv-retire.js');

function clock() {
  let t = 0;
  return { now: () => t, sleep: async (ms) => { t += ms; }, at: () => t };
}

test('a cold boot that answers health after four minutes counts as healthy', async () => {
  const c = clock();
  const ok = await retire.awaitEngineHealthy({ isHealthy: async () => c.at() >= 240000, engineAlive: () => true, now: c.now, sleep: c.sleep });
  assert.equal(ok, true);
});

test('an engine that exits stops the wait at once, unhealthy', async () => {
  const c = clock();
  const ok = await retire.awaitEngineHealthy({ isHealthy: async () => false, engineAlive: () => c.at() < 3000, now: c.now, sleep: c.sleep });
  assert.equal(ok, false);
  assert.ok(c.at() < 10000);
});

test('an engine that never answers is unhealthy after the ten minute window', async () => {
  const c = clock();
  const ok = await retire.awaitEngineHealthy({ isHealthy: async () => false, engineAlive: () => true, now: c.now, sleep: c.sleep });
  assert.equal(ok, false);
  assert.ok(c.at() >= retire.HEALTH_WINDOW_MS);
});
