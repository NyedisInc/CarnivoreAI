import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const main = readFileSync(new URL('../../../macOS/main.js', import.meta.url), 'utf8');
const mgr = readFileSync(new URL('../../../macOS/server-manager.js', import.meta.url), 'utf8');

assert.match(main, /const STEADY_HEALTH_POLL_MS = 15000;/);
assert.doesNotMatch(main, /pollInterval = 5000/, 'a 5 s steady poll came back');
assert.match(main, /pollInterval = STEADY_HEALTH_POLL_MS;/);
assert.match(mgr, /EXPOSURE_REFRESH_EVERY = 4;/);
assert.match(mgr, /healthProbeCount % EXPOSURE_REFRESH_EVERY !== 0/);
assert.match(mgr, /this\.reportedBind = null;\n\s+this\.reportedSetupStatus = null;\n\s+this\.reportedJoined = null;\n\s+this\.reportedRebindRequested = false;\n\s+return null;/,
  'an unreachable server must clear the cached exposure');
console.log('health-poll-cadence: passed');
