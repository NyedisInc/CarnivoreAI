
'use strict';

const fs = require('fs');
const path = require('path');

const STATE_FILE = 'venv-retire.json';

const REQUIRED_HEALTHY = 3;

function readState(userData) {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(userData, STATE_FILE), 'utf8'));
    const count = Number.isInteger(raw.count) && raw.count > 0 ? raw.count : 0;
    return { count, pending: raw.pending === true };
  } catch (err) {
    return { count: 0, pending: false };
  }
}

function writeState(userData, state) {
  fs.mkdirSync(userData, { recursive: true });
  const file = path.join(userData, STATE_FILE);
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(state)}\n`, { mode: 0o600 });
  fs.renameSync(tmp, file);
}

function beginLaunch({ userData, hasPayload }) {
  if (!hasPayload) return { count: 0 };
  const prior = readState(userData);
  const count = prior.pending ? 0 : prior.count;
  try {
    writeState(userData, { count, pending: true });
  } catch (err) {
    console.warn('[venv-retire] could not mark the launch:', err.message);
  }
  return { count };
}

function recordLaunch({ userData, hasPayload, healthy }) {
  if (!hasPayload) return { count: 0, retire: false };
  const prior = readState(userData);
  const count = healthy === null ? prior.count : (healthy ? prior.count + 1 : 0);
  writeState(userData, { count, pending: false });
  return { count, retire: count >= REQUIRED_HEALTHY };
}

const HEALTH_WINDOW_MS = 10 * 60 * 1000;

async function awaitEngineHealthy({ isHealthy, engineAlive, windowMs = HEALTH_WINDOW_MS, intervalMs = 500,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)), now = Date.now }) {
  const start = now();
  while (now() - start < windowMs) {
    if (!engineAlive()) return false;
    if (await isHealthy()) return true;
    await sleep(intervalMs);
  }
  return false;
}

function retireVenv({ serverDir }) {
  const venv = path.join(serverDir, 'venv');
  let st;
  try {
    st = fs.lstatSync(venv);
  } catch (err) {
    return { retired: false, reason: 'absent' };
  }
  if (!st.isDirectory()) return { retired: false, reason: 'not-a-folder' };
  fs.rmSync(path.join(serverDir, '.deps-hash'), { force: true });
  fs.rmSync(venv, { recursive: true, force: true });
  return { retired: true };
}

async function recordVenvOutcome({ serverManager, userData, serverDir }) {
  try {
    const hasPayload = !!serverManager.payload;
    let healthy = false;
    if (hasPayload && !serverManager.startBlockedReason) {
      healthy = serverManager.ownedProcess ? await awaitEngineHealthy({
        isHealthy: () => serverManager.getHealth(), engineAlive: () => serverManager.ownedProcess }) : null;
    }
    const outcome = recordLaunch({ userData, hasPayload, healthy });
    if (outcome.retire) {
      const done = retireVenv({ serverDir });
      console.log(`[venv-retire] healthy payload launches: ${outcome.count}; venv ${done.retired ? 'retired' : `kept (${done.reason})`}`);
    }
  } catch (err) {
    console.warn('[venv-retire] could not record the launch:', err.message);
  }
}

module.exports = { recordVenvOutcome, STATE_FILE, REQUIRED_HEALTHY, HEALTH_WINDOW_MS, awaitEngineHealthy, readState, beginLaunch, recordLaunch, retireVenv };
