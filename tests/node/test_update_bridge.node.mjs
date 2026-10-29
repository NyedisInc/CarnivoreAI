import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { createUpdateBridge } = require('../../macOS/update-bridge.js');

let passes = 0, failures = 0;
async function test(name, fn) {
  try { await fn(); passes++; } catch (e) { failures++; console.error(`FAIL: ${name}\n  ${e.stack || e.message}`); }
}

function rig() {
  const calls = [];
  const state = { state: 'idle', version: null, percent: null, checkedAt: null, detail: null };
  const ran = [];
  const controller = {
    getState: () => state,
    check: async () => { ran.push('check'); },
    install: async () => { ran.push('install'); },
    applyAutoUpdate: () => { ran.push('config'); },
  };
  const api = { sendAuthed: async (route, body, method) => { calls.push({ route, body, method }); return { reachable: true, data: {} }; } };
  const holder = { api };
  const bridge = createUpdateBridge({ controller, getApi: () => holder.api, appVersion: () => '1.16.2' });
  return { bridge, state, calls, ran, holder };
}
const ok = (data) => ({ status: 'ok', data });

await test('a state change is pushed once to the state route with the server shape', async () => {
  const r = rig();
  r.state.state = 'available'; r.state.version = '1.17.0'; r.state.checkedAt = 5000;
  await r.bridge.push();
  await r.bridge.push();
  assert.equal(r.calls.length, 1);
  assert.deepEqual(r.calls[0], { route: '/api/v1/app-update/state', method: 'POST', body: {
    state: 'available', current_version: '1.16.2', latest_version: '1.17.0', percent: null, detail: null, checked_at: 5 } });
});

await test('download progress is pushed in steps, not per tick', async () => {
  const r = rig();
  r.state.state = 'downloading'; r.state.percent = 0;
  await r.bridge.push();
  for (const p of [1, 2, 3, 4]) { r.state.percent = p; await r.bridge.push(); }
  assert.equal(r.calls.length, 1);
  r.state.percent = 5; await r.bridge.push();
  assert.equal(r.calls.length, 2);
});

await test('no trusted server connection: nothing is sent and nothing throws', async () => {
  const r = rig();
  r.holder.api = null;
  await r.bridge.push();
  assert.equal(r.calls.length, 0);
});

await test('the first status read is only a baseline: an older queued command is not replayed', async () => {
  const r = rig();
  await r.bridge.onServerStatus(ok({ command_seq: 7, command: 'install', attached: true, state: 'idle' }));
  assert.deepEqual(r.ran, []);
});

await test('a newer command runs once; re-reading the same seq does not run it again', async () => {
  const r = rig();
  await r.bridge.onServerStatus(ok({ command_seq: 1, command: 'check', attached: true, state: 'idle' }));
  await r.bridge.onServerStatus(ok({ command_seq: 2, command: 'check', attached: true, state: 'idle' }));
  await r.bridge.onServerStatus(ok({ command_seq: 2, command: 'check', attached: true, state: 'idle' }));
  await r.bridge.onServerStatus(ok({ command_seq: 3, command: 'install', attached: true, state: 'idle' }));
  await r.bridge.onServerStatus(ok({ command_seq: 4, command: 'config', attached: true, state: 'idle' }));
  assert.deepEqual(r.ran, ['check', 'install', 'config']);
});

await test('a server that never heard from this app, or holds another state, gets ours pushed', async () => {
  const r = rig();
  await r.bridge.onServerStatus(ok({ command_seq: 0, command: null, attached: false, state: 'unavailable' }));
  assert.equal(r.calls.length, 1);
  await r.bridge.onServerStatus(ok({ command_seq: 0, command: null, attached: true, state: 'idle' }));
  assert.equal(r.calls.length, 1, 'in sync: no push');
  await r.bridge.onServerStatus(ok({ command_seq: 0, command: null, attached: true, state: 'current' }));
  assert.equal(r.calls.length, 2, 'a different state is re-pushed');
});

await test('an unreadable status (older server, 404) is ignored', async () => {
  const r = rig();
  await r.bridge.onServerStatus({ status: 'missing', data: null });
  await r.bridge.onServerStatus(null);
  assert.equal(r.calls.length, 0);
});

console.log(`${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
