'use strict';

const net = require('net');

function hasListener(port, timeoutMs = 1000) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: '127.0.0.1' });
    const done = (answer) => { socket.destroy(); resolve(answer); };
    socket.setTimeout(timeoutMs, () => done(true));
    socket.once('connect', () => done(true));
    socket.once('error', (err) => done(!(err && err.code === 'ECONNREFUSED')));
  });
}

async function waitForStaleBind(deps) {
  const sleep = deps.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const now = deps.now || Date.now;
  const budgetMs = deps.budgetMs === undefined ? 45000 : deps.budgetMs;
  const pollMs = deps.pollMs === undefined ? 1000 : deps.pollMs;
  if (await deps.hasListener()) return false;
  if (deps.onWaiting) deps.onWaiting();
  const deadline = now() + budgetMs;
  while (now() < deadline) {
    await sleep(pollMs);
    if (await deps.getHealth()) return false;
    if (await deps.hasListener()) return false;
    if (!(await deps.isBound())) return true;
  }
  return false;
}

async function engineInUse(manager, port, overrides = {}) {
  if (!(await manager.engineIsUp(port))) return false;
  if (await manager.getHealth()) return true;
  const before = manager.state;
  let freed = false;
  try {
    freed = await waitForStaleBind({
      isBound: () => manager.isPortInUse(port),
      hasListener: () => hasListener(port),
      getHealth: () => manager.getHealth(),
      onWaiting: () => {
        manager.state = 'starting';
        manager.startWait = true;
        const note = { key: 'desktop.engine_wait.port_freeing', params: { port: String(port) } };
        if (typeof manager.onStartNote === 'function') manager.onStartNote(note);
      },
      ...overrides,
    });
  } finally {
    manager.startWait = false;
    manager.startNoteText = null;
  }
  if (!freed && manager.state === 'starting') manager.state = before;
  return !freed;
}

module.exports = { hasListener, waitForStaleBind, engineInUse };
