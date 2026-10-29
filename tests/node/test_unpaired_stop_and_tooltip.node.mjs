import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const { stopEngine } = require(path.join(macDir, 'engine', 'engine-lifecycle.js'));
const { describeSignals } = require(path.join(macDir, 'tray-status.js'));
const PORT = 5041;

const portTrust = require(path.join(macDir, 'tray-menu', 'port-trust.js'));
const { execFile } = require('node:child_process');
const FAKE_HEALTH = { status: 'ok', uptime: 5, version: '1.2.3' };

async function listen(port) {
  const child = spawn(process.execPath, ['-e', `require('net').createServer().listen(${port}, '127.0.0.1')`], { stdio: 'ignore' });
  const probe = () => new Promise((resolve) => {
    const s = net.connect(port, '127.0.0.1', () => { s.destroy(); resolve(true); });
    s.on('error', () => resolve(false));
  });
  for (let i = 0; i < 50 && !(await probe()); i += 1) await new Promise((r) => setTimeout(r, 100));
  return { child, probe };
}

function managerFor(port, probe, record, health = FAKE_HEALTH) {
  return {
    ownedProcess: false, engineRecord: record, getPort: () => port, engineIsUp: probe, getHealth: async () => health,
    readSetupFacts: () => ({ envText: '', configText: '{}', pairedExists: false }), getSetupVerdict: () => ({ status: 'incomplete' }),
  };
}

test('an un-adopted same-user listener is refused and survives the unpaired stop', async () => {
  const { child, probe } = await listen(PORT);
  try {
    const r = await stopEngine(managerFor(PORT, probe, null), { getApi: () => null });
    assert.equal(r.stopped, false, JSON.stringify(r));
    assert.equal(await probe(), true, 'the stranger must still be listening');
  } finally { child.kill('SIGKILL'); }
});

test('a record whose pid is not the listener, whose port moved, or with a second listener is refused', async () => {
  const { child, probe } = await listen(PORT);
  const second = await listen(PORT + 1);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: PORT, version: '1.2.3' };
    for (const [label, mgr] of [
      ['other pid', managerFor(PORT, probe, { ...good, pid: second.child.pid })],
      ['stale start', managerFor(PORT, probe, { ...good, start: 'Mon Jan  1 00:00:00 2001' })],
      ['port moved', { ...managerFor(PORT, probe, good), getPort: () => PORT + 1 }],
      ['other version', managerFor(PORT, probe, good, { ...FAKE_HEALTH, version: '9.9.9' })],
    ]) {
      const r = await stopEngine(mgr, { getApi: () => null });
      assert.equal(r.stopped, false, `${label}: ${JSON.stringify(r)}`);
    }
    assert.equal(await probe(), true);
    assert.equal(await second.probe(), true);
  } finally { child.kill('SIGKILL'); second.child.kill('SIGKILL'); }
});

test('the listener own setup_status cannot steer the stop onto the kill path, and a signed-in client keeps the route', async () => {
  const { child, probe } = await listen(PORT);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: PORT, version: '1.2.3' };
    const complete = { ...managerFor(PORT, probe, good), readSetupFacts: () => ({ envText: 'TOTP_SECRET=a\nJWT_SECRET=b', configText: '{}', pairedExists: true }), getSetupVerdict: () => ({ status: 'incomplete' }) };
    assert.equal((await stopEngine(complete, { getApi: () => null })).stopped, false);
    const signedIn = managerFor(PORT, probe, good);
    const r = await stopEngine(signedIn, { getApi: () => ({ sendAuthed: async () => ({ reachable: false, error: 'x' }) }) });
    assert.equal(r.outcome, 'route-failed');
    assert.equal(await probe(), true);
  } finally { child.kill('SIGKILL'); }
});

test('the exact adopted engine on an unfinished setup is stopped with no tray client', async () => {
  const { child, probe } = await listen(PORT);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: PORT, version: '1.2.3' };
    const r = await stopEngine(managerFor(PORT, probe, good), { getApi: () => null });
    assert.equal(r.stopped, true, JSON.stringify(r));
    assert.equal(await probe(), false);
  } finally { child.kill('SIGKILL'); }
});

test('tooltip on an unfinished setup with an unread session list says cannot determine', () => {
  const s = describeSignals({ serverState: 'running', setupStatus: 'incomplete', sessionsReachable: false, sessions: null });
  assert.equal(s.sessions, 'cannot determine');
});
