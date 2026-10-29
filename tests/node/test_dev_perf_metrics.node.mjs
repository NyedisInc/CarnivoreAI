import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { startDevPerf, INTERVAL_MS } = require(path.join(here, '..', '..', 'macOS', 'dev-perf.js'));

const metrics = [{ pid: 7, type: 'Tab', name: 'Carnivore', cpu: { percentCPUUsage: 3.456, idleWakeupsPerSecond: 12 }, memory: { workingSetSize: 20480 } }];
function rig(env) {
  const lines = []; const files = []; const timers = [];
  const app = { getPath: () => '/ud', getAppMetrics: () => metrics };
  const handle = startDevPerf({
    app, env,
    writerFactory: (p) => { files.push(p); return { write: (l) => lines.push(l), end() {} }; },
    setInterval: (fn, ms) => { const t = { fn, ms, unref() { this.unrefd = true; } }; timers.push(t); return t; },
    now: () => 0,
  });
  return { handle, lines, files, timers };
}

test('env off: no timer, no file', () => {
  const r = rig({});
  assert.equal(r.handle, null);
  assert.equal(r.timers.length, 0);
  assert.equal(r.files.length, 0);
});

test('env on (either name): one tick writes one mapped line to logs/dev-perf.log', () => {
  for (const env of [{ CARNIVORE_DEV_PERF_HOOKS: '1' }, { CLOUDE_DEV_PERF_HOOKS: '1' }]) {
    const r = rig(env);
    assert.deepEqual(r.files, [path.join('/ud', 'logs', 'dev-perf.log')]);
    assert.equal(r.timers.length, 1);
    assert.equal(r.timers[0].ms, INTERVAL_MS);
    assert.equal(r.timers[0].unrefd, true);
    r.timers[0].fn();
    assert.equal(r.lines.length, 1);
    assert.deepEqual(JSON.parse(r.lines[0]), { t: '1970-01-01T00:00:00.000Z', metrics: [{ pid: 7, type: 'Tab', name: 'Carnivore', cpu_pct: 3.5, idle_wakeups_per_s: 12, rss_mb: 20 }] });
  }
});
