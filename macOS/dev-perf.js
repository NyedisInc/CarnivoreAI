'use strict';


const path = require('path');

const INTERVAL_MS = 10000;
const ON = new Set(['1', 'true', 'yes', 'on']);

function enabled(env) {
  return ['CARNIVORE_DEV_PERF_HOOKS', 'CLOUDE_DEV_PERF_HOOKS'].some((k) => ON.has(String(env[k] || '').trim().toLowerCase()));
}

function mapMetrics(metrics) {
  return metrics.map((m) => ({
    pid: m.pid,
    type: m.type,
    name: m.name || m.serviceName || '',
    cpu_pct: Math.round(((m.cpu && m.cpu.percentCPUUsage) || 0) * 10) / 10,
    idle_wakeups_per_s: (m.cpu && m.cpu.idleWakeupsPerSecond) || 0,
    rss_mb: Math.round((((m.memory && m.memory.workingSetSize) || 0) / 1024) * 10) / 10,
  }));
}

function startDevPerf({ app, env = process.env, writerFactory, setInterval: setIntervalFn = setInterval, now = Date.now }) {
  if (!enabled(env)) return null;
  const file = path.join(app.getPath('userData'), 'logs', 'dev-perf.log');
  const makeWriter = writerFactory || ((p) => {
    require('fs').mkdirSync(path.dirname(p), { recursive: true });
    const { RotatingLogWriter } = require('./log-rotation');
    return new RotatingLogWriter(p, { maxBytes: 1024 * 1024, backupCount: 2 });
  });
  const writer = makeWriter(file);
  const timer = setIntervalFn(() => {
    try {
      writer.write(`${JSON.stringify({ t: new Date(now()).toISOString(), metrics: mapMetrics(app.getAppMetrics()) })}\n`);
    } catch (err) {
      console.warn(`[dev-perf] tick failed: ${err.message}`);
    }
  }, INTERVAL_MS);
  if (timer && timer.unref) timer.unref();
  return { stop() { clearInterval(timer); writer.end(); } };
}

module.exports = { startDevPerf, mapMetrics, enabled, INTERVAL_MS };
