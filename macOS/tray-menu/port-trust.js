
'use strict';

const path = require('path');

const KILL_GRACE_MS = 3000;
const NEVER_KILL = Object.freeze(['tmux', 'Electron', 'Carnivore', 'launchd', 'kernel_task']);

function parseLsof(stdout) {
  const out = [];
  let cur = null;
  for (const line of String(stdout || '').split('\n')) {
    const tag = line[0];
    const value = line.slice(1);
    if (tag === 'p') {
      cur = { pid: parseInt(value, 10), command: null, uid: null };
      if (Number.isInteger(cur.pid)) out.push(cur);
    } else if (cur && tag === 'c') {
      cur.command = value;
    } else if (cur && tag === 'u') {
      const uid = parseInt(value, 10);
      cur.uid = Number.isInteger(uid) ? uid : null;
    }
  }
  return out;
}

function isCarnivoreHealth(body) {
  return Boolean(body && typeof body.status === 'string' && typeof body.uptime === 'number'
    && typeof body.version === 'string');
}

/* another user */
function holderRefusal(holders, myUid) {
  if (!Array.isArray(holders) || holders.length === 0) return { reason: 'unknown', holder: null };
  const stranger = holders.find((h) => h.uid !== myUid);
  return stranger ? { reason: 'not_yours', holder: stranger } : null;
}

/* PORT_HOLDER_NOT_YOURS */
function holderError(refusal, port) {
  const who = refusal.holder ? ` (${describeHolder(refusal.holder)})` : ' and Carnivore could not confirm it is yours';
  const err = new Error(`Another program holds port ${port}${who}. Carnivore will not open a window onto it or stop it. Stop that program, or change the port in Settings.`);
  err.code = 'PORT_HOLDER_NOT_YOURS';
  err.port = port;
  return err;
}

/* CANNOT DETERMINE could not be read */
function judgePort(input) {
  const holders = Array.isArray(input.holders) ? input.holders : null;
  const refusal = holderRefusal(holders, input.myUid);
  if (refusal && refusal.reason === 'unknown') return { trusted: null, reason: 'unknown', holder: null };
  if (refusal) return { trusted: false, reason: 'not_yours', holder: refusal.holder };
  if (!isCarnivoreHealth(input.health)) return { trusted: false, reason: 'not_carnivore', holder: holders[0] };
  return { trusted: true, reason: 'ok', holder: holders[0] };
}

function describeHolder(holder) {
  if (!holder) return 'unknown process';
  const bits = [holder.command, holder.uid === null || holder.uid === undefined ? null : `uid ${holder.uid}`]
    .filter(Boolean).join(', ');
  return bits ? `PID ${holder.pid} (${bits})` : `PID ${holder.pid}`;
}

function run(execFile, file, args) {
  return new Promise((resolve) => {
    execFile(file, args, { timeout: 5000 }, (error, stdout) => resolve(error ? null : String(stdout || '')));
  });
}

async function listeners(port, deps) {
  if (!Number.isInteger(port)) return null;
  const out = await run(deps.execFile, '/usr/sbin/lsof', ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-F', 'pcu']);
  return out === null ? [] : parseLsof(out);
}

async function processIdentity(pid, deps) {
  const out = await run(deps.execFile, '/bin/ps', ['-o', 'lstart=,comm=', '-p', String(pid)]);
  const line = out && out.trim();
  if (!line) return null;
  const parts = line.split(/\s+/);
  return { start: parts.slice(0, 5).join(' '), exe: parts.slice(5).join(' ') };
}

async function identifyHolder(port, deps) {
  const found = await listeners(port, deps);
  if (!found || found.length === 0) return null;
  const holder = found[0];
  const ident = await processIdentity(holder.pid, deps);
  if (!ident) return null;
  return { pid: holder.pid, uid: holder.uid, start: ident.start, exe: ident.exe, name: path.basename(ident.exe) };
}

function killRefusal(holder, me) {
  if (!holder) return 'nothing is listening on the port';
  if (holder.uid !== me.myUid) return `PID ${holder.pid} belongs to another user (uid ${holder.uid})`;
  if (holder.pid === me.myPid || NEVER_KILL.includes(holder.name)) return `PID ${holder.pid} (${holder.name}) is never stopped from here`;
  return null;
}

async function killHolder(port, confirmed, deps) {
  const now = await identifyHolder(port, deps);
  if (!now || now.pid !== confirmed.pid || now.start !== confirmed.start || now.uid !== confirmed.uid) {
    return { stopped: false, detail: 'the process on the port changed since you confirmed; nothing was stopped' };
  }
  const refusal = killRefusal(now, deps);
  if (refusal) return { stopped: false, detail: refusal };
  try {
    deps.kill(now.pid, 'SIGTERM');
  } catch (error) {
    return { stopped: false, detail: `SIGTERM failed: ${error.message}` };
  }
  await deps.sleep(KILL_GRACE_MS);
  const after = await processIdentity(now.pid, deps);
  if (after && after.start === now.start) {
    try {
      deps.kill(now.pid, 'SIGKILL');
    } catch (error) {
      return { stopped: false, detail: `SIGKILL failed: ${error.message}` };
    }
  }
  return { stopped: true, detail: `stopped PID ${now.pid} (${now.name})` };
}

module.exports = {
  KILL_GRACE_MS, NEVER_KILL, parseLsof, isCarnivoreHealth, holderRefusal, holderError, judgePort, describeHolder, listeners, processIdentity,
  identifyHolder, killRefusal, killHolder,
};
