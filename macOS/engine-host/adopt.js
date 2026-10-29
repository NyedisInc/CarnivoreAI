'use strict';

async function probeEngine({ health, bind, listenPid }) {
  const answer = await health();
  if (answer) return { up: true, via: 'health', health: answer, pid: await listenPid() };
  if (await bind()) return { up: true, via: 'bind', health: null, pid: await listenPid() };
  return { up: false, via: 'none', health: null, pid: null };
}

const listenPidCommand = (port) => `lsof -nP -iTCP:${port} -sTCP:LISTEN -t`;

module.exports = { probeEngine, listenPidCommand };
