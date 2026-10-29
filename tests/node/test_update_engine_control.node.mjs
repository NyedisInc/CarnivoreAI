import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { createUpdateEngineControl } = require('../../macOS/update-engine-control.js');

const events = [];
const sm = { beginQuit: () => events.push('beginQuit'), cancelQuit: () => events.push('cancelQuit') };
let stopResult = { stopped: true };
const ctl = createUpdateEngineControl({
  getServerManager: () => sm,
  getHost: () => ({ stop: async () => { events.push('host.stop'); return stopResult; }, start: async () => { events.push('host.start'); } }),
  engineApi: () => null,
  stopStatsPolling: () => events.push('stopPoll'),
  startStatsPolling: () => events.push('poll'),
  refreshTray: () => events.push('tray'),
  setSystemQuit: (v) => events.push('systemQuit ' + v),
  setWindowQuitting: (v) => events.push('windowQuitting ' + v)
});

await ctl.stopForInstall();
assert.deepEqual(events.splice(0), ['beginQuit', 'stopPoll', 'host.stop', 'systemQuit true']);

stopResult = { stopped: false };
await assert.rejects(ctl.stopForInstall(), /did not stop/);
assert.deepEqual(events.splice(0), ['beginQuit', 'stopPoll', 'host.stop']);

await ctl.restartAfterFailedInstall();
assert.deepEqual(events.splice(0), ['cancelQuit', 'systemQuit false', 'windowQuitting false', 'host.start', 'poll', 'tray']);

const none = createUpdateEngineControl({ getServerManager: () => null, getHost: () => { throw new Error('no host'); } });
await none.stopForInstall();
await none.restartAfterFailedInstall();
console.log('update-engine-control: ok');
