// WHY THIS FILE EXISTS
// we know nothing

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const macDir = path.join(repoRoot, 'macOS');
const assetsDir = path.join(macDir, 'assets');

const trayStatus = require(path.join(macDir, 'tray-status.js'));
const { TrayApiClient } = require(path.join(macDir, 'tray-api.js'));

let passed = 0;
const failures = [];

async function test(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log('  ok   ' + name);
  } catch (error) {
    failures.push({ name, error });
    console.log('  FAIL ' + name + ': ' + error.message);
  }
}

function session(status) {
  return { session_name: 'sess-' + status, activity_status: status };
}

const RUNNING = { serverState: 'running', sessionsReachable: true, updateState: 'current' };

console.log('tray-status: the false green this feature exists to kill');

await test('an UNREACHABLE session list is unknown, never ok', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'running',
    sessions: null,
    sessionsReachable: false,
    updateState: 'current',
  });
  assert.equal(
    derived.state,
    'unknown',
    'a server that could not be polled must NOT render as healthy'
  );
  assert.notEqual(derived.state, 'ok');
});

await test('an EMPTY session list is ok, never unknown', () => {
  const derived = trayStatus.deriveTrayState({ ...RUNNING, sessions: [] });
  assert.equal(
    derived.state,
    'ok',
    'the server was asked and genuinely has nothing running; that is a real ' +
      'measurement and must not be downgraded to cannot-determine'
  );
});

await test('empty-and-reachable and unreachable do NOT collapse together', () => {
  const measured = trayStatus.deriveTrayState({ ...RUNNING, sessions: [] });
  const unmeasured = trayStatus.deriveTrayState({
    serverState: 'running',
    sessions: null,
    sessionsReachable: false,
    updateState: 'current',
  });
  assert.notEqual(
    measured.state,
    unmeasured.state,
    'both have zero sessions needing attention; they must still differ'
  );
});

await test('a session reporting unknown status is unknown, not ok', () => {
  const derived = trayStatus.deriveTrayState({
    ...RUNNING,
    sessions: [session('idle'), session('unknown')],
  });
  assert.equal(derived.state, 'unknown');
  assert.equal(derived.unknownCount, 1);
});

console.log('tray-status: attention detection');

for (const status of ['question', 'finished_unread', 'dead']) {
  await test(`a "${status}" session raises the attention state`, () => {
    const derived = trayStatus.deriveTrayState({
      ...RUNNING,
      sessions: [session('working'), session(status)],
    });
    assert.equal(derived.state, 'attention');
    assert.equal(derived.attentionCount, 1);
  });
}

await test('working and idle sessions alone do not raise attention', () => {
  const derived = trayStatus.deriveTrayState({
    ...RUNNING,
    sessions: [session('working'), session('working_subagent'), session('idle')],
  });
  assert.equal(derived.state, 'ok');
  assert.equal(derived.attentionCount, 0);
});

await test('attention outranks an available update', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'running',
    sessionsReachable: true,
    sessions: [session('question')],
    updateState: 'ready',
  });
  assert.equal(derived.state, 'attention');
});

await test('an available update surfaces when nothing needs attention', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'running',
    sessionsReachable: true,
    sessions: [session('idle')],
    updateState: 'ready',
  });
  assert.equal(derived.state, 'update');
});

await test('an undeterminable UPDATE check does not pin the icon to unknown', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'running',
    sessionsReachable: true,
    sessions: [session('idle')],
    updateState: null,
  });
  assert.equal(derived.state, 'ok');
  const signals = trayStatus.describeSignals({
    serverState: 'running',
    sessionsReachable: true,
    sessions: [session('idle')],
    updateState: null,
  });
  assert.equal(
    signals.update,
    'cannot determine',
    'the unknown must still be STATED even though it does not drive the icon'
  );
});

console.log('tray-status: server state precedence');

await test('a stop the user asked for is stopped, not crashed', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'stopped',
    lastExitUnexpected: false,
  });
  assert.equal(derived.state, 'stopped');
});

await test('an exit nobody asked for is crashed, not stopped', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'stopped',
    lastExitUnexpected: true,
  });
  assert.equal(
    derived.state,
    'crashed',
    'a server that died on its own must not look like one the user stopped'
  );
});

await test('starting is its own state', () => {
  const derived = trayStatus.deriveTrayState({ serverState: 'starting' });
  assert.equal(derived.state, 'starting');
});

await test('a non-running server reports sessions as cannot determine', () => {
  const signals = trayStatus.describeSignals({ serverState: 'stopped' });
  assert.ok(
    signals.sessions.includes('cannot determine'),
    'got: ' + signals.sessions
  );
});

console.log('tray-status: the tooltip states every signal');

await test('the tooltip names server, sessions and update on separate lines', () => {
  const tip = trayStatus.buildTooltip({
    serverState: 'running',
    sessionsReachable: false,
    sessions: null,
    updateState: null,
  });
  const lines = tip.split('\n');
  assert.ok(lines.some((l) => l.startsWith('Server:')), tip);
  assert.ok(lines.some((l) => l.startsWith('Sessions:')), tip);
  assert.ok(lines.some((l) => l.startsWith('Update:')), tip);
  assert.ok(
    tip.includes('cannot determine'),
    'an unmeasured signal must SAY so in the tooltip:\n' + tip
  );
});

console.log('tray-status: icon (issue #315 - fixed mark, no per-state swap)');

await test('the old per-state icon folder is gone', () => {
  const oldPerStateIconDir = path.join(assetsDir, 'tray');
  assert.equal(
    fs.existsSync(oldPerStateIconDir),
    false,
    'the folder that held the deleted status-dot variants still exists; a ' +
      'directory nobody loads is the kind of thing that silently rots'
  );
});

await test('the single fixed template icon exists at both scales', () => {
  for (const file of ['iconTemplate.png', 'iconTemplate@2x.png']) {
    assert.ok(
      fs.existsSync(path.join(assetsDir, file)),
      `missing the fixed tray icon: ${file}`
    );
  }
});

await test('deriveTrayState and buildTooltip still work with no icon involved', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'running',
    sessionsReachable: true,
    sessions: [session('question')],
    updateState: 'current',
  });
  assert.equal(derived.state, 'attention');
  const tip = trayStatus.buildTooltip({
    serverState: 'running',
    sessionsReachable: true,
    sessions: [session('question')],
    updateState: 'current',
  });
  assert.ok(tip.includes('Server:'), tip);
});

console.log('tray-api: authentication and three outcomes');

function makeFetch(script) {
  const calls = [];
  let index = 0;
  const fetchImpl = async (url, options) => {
    const opts = options || {};
    calls.push({
      url,
      method: opts.method || 'GET',
      auth: (opts.headers || {}).Authorization || null,
      body: opts.body ? JSON.parse(opts.body) : null,
    });
    const next = script[Math.min(index, script.length - 1)];
    index += 1;
    return {
      ok: next.status >= 200 && next.status < 300,
      status: next.status,
      json: async () => next.body,
    };
  };
  return { fetchImpl, calls };
}

await test('the tray authenticates by spending a TOTP code for a token', async () => {
  const { fetchImpl, calls } = makeFetch([
    { status: 200, body: { access_token: 'AT', refresh_token: 'RT', expires_in: 14400 } },
    { status: 200, body: [session('question')] },
  ]);
  const client = new TrayApiClient({
    baseUrl: 'http://127.0.0.1:8000',
    getOtp: () => '123456',
    fetchImpl,
  });

  const result = await client.fetchSessions();
  assert.equal(result.reachable, true);
  assert.equal(result.sessions.length, 1);

  assert.ok(calls[0].url.endsWith('/api/v1/auth/verify'), calls[0].url);
  assert.deepEqual(calls[0].body, { code: '123456' });
  assert.equal(calls[1].auth, 'Bearer AT', 'the session call was not authenticated');
});

await test('the tray reads the pushed listing snapshot, not a fresh /sessions/list gather', async () => {
  const snapshot = {
    stream: 's', seq: 1,
    collections: { list: { ok: true, rows: [session('question'), session('idle')] } },
  };
  const { fetchImpl, calls } = makeFetch([
    { status: 200, body: { access_token: 'AT', refresh_token: 'RT', expires_in: 14400 } },
    { status: 200, body: snapshot },
  ]);
  const client = new TrayApiClient({ baseUrl: 'http://127.0.0.1:8000', getOtp: () => '123456', fetchImpl });
  const result = await client.fetchSessions();
  assert.equal(result.reachable, true);
  assert.equal(result.sessions.length, 2);
  const polled = calls.map((c) => c.url);
  assert.ok(polled.some((u) => u.includes('/sessions/listing?max_age=')), polled.join());
  assert.ok(!polled.some((u) => u.endsWith('/sessions/list')), 'forced a fresh gather: ' + polled.join());
});

await test('a listing snapshot whose list collection failed falls back to /sessions/list', async () => {
  const { fetchImpl, calls } = makeFetch([
    { status: 200, body: { access_token: 'AT', refresh_token: 'RT', expires_in: 14400 } },
    { status: 200, body: { collections: { list: { ok: false, rows: [] } } } },
    { status: 200, body: [session('question')] },
  ]);
  const client = new TrayApiClient({ baseUrl: 'http://127.0.0.1:8000', getOtp: () => '123456', fetchImpl });
  const result = await client.fetchSessions();
  assert.equal(result.sessions.length, 1);
  assert.ok(calls[calls.length - 1].url.endsWith('/sessions/list'));
});

await test('a cached token is reused instead of spending another TOTP code', async () => {
  const { fetchImpl, calls } = makeFetch([
    { status: 200, body: { access_token: 'AT', refresh_token: 'RT', expires_in: 14400 } },
    { status: 200, body: [] },
    { status: 200, body: [] },
  ]);
  const client = new TrayApiClient({
    baseUrl: 'http://127.0.0.1:8000',
    getOtp: () => '123456',
    fetchImpl,
  });

  await client.fetchSessions();
  await client.fetchSessions();

  const verifies = calls.filter((c) => c.url.endsWith('/auth/verify'));
  assert.equal(
    verifies.length,
    1,
    'TOTP codes are single use and shared with his browser login; polling ' +
      'must not burn one per poll'
  );
});

await test('no TOTP secret is CANNOT DETERMINE, not an empty session list', async () => {
  const { fetchImpl } = makeFetch([{ status: 200, body: [] }]);
  const client = new TrayApiClient({
    baseUrl: 'http://127.0.0.1:8000',
    getOtp: () => null,
    fetchImpl,
  });

  const result = await client.fetchSessions();
  assert.equal(result.reachable, false);
  assert.equal(result.sessions, null, 'must not fabricate an empty list');
  assert.ok(result.error, 'a failure must carry a reason');
});

await test('a rejected TOTP code reports unreachable rather than healthy', async () => {
  const { fetchImpl } = makeFetch([{ status: 401, body: { detail: 'bad code' } }]);
  const client = new TrayApiClient({
    baseUrl: 'http://127.0.0.1:8000',
    getOtp: () => '000000',
    fetchImpl,
  });

  const result = await client.fetchSessions();
  assert.equal(result.reachable, false);
  assert.equal(result.sessions, null);
});

await test('a transport failure is unreachable, never an empty list', async () => {
  const client = new TrayApiClient({
    baseUrl: 'http://127.0.0.1:8000',
    getOtp: () => '123456',
    fetchImpl: async () => {
      throw new Error('ECONNREFUSED');
    },
  });

  const result = await client.fetchSessions();
  assert.equal(result.reachable, false);
  assert.equal(result.sessions, null);
  assert.ok(String(result.error).includes('ECONNREFUSED'), result.error);
});

await test('changing the bind address discards the cached token', async () => {
  const { fetchImpl, calls } = makeFetch([
    { status: 200, body: { access_token: 'AT', refresh_token: 'RT', expires_in: 14400 } },
    { status: 200, body: [] },
    { status: 200, body: { access_token: 'AT2', refresh_token: 'RT2', expires_in: 14400 } },
    { status: 200, body: [] },
  ]);
  const client = new TrayApiClient({
    baseUrl: 'http://127.0.0.1:8000',
    getOtp: () => '123456',
    fetchImpl,
  });

  await client.fetchSessions();
  client.setBaseUrl('http://10.0.1.5:8000');
  await client.fetchSessions();

  const verifies = calls.filter((c) => c.url.endsWith('/auth/verify'));
  assert.equal(verifies.length, 2, 'a token minted for one origin was replayed at another');
});

await test('a downloading update also lights the update icon', () => {
  const derived = trayStatus.deriveTrayState({
    serverState: 'running', sessionsReachable: true, sessions: [session('idle')],
    updateState: 'downloading',
  });
  assert.equal(derived.state, 'update');
  const idle = trayStatus.deriveTrayState({
    serverState: 'running', sessionsReachable: true, sessions: [session('idle')],
    updateState: 'not_configured',
  });
  assert.equal(idle.state, 'ok');
});

console.log('');
console.log('tray-status: ' + passed + ' passed, ' + failures.length + ' failed');
process.exit(failures.length > 0 ? 1 : 0);
