
'use strict';

const model = require('./model');

const ENGINE_WAIT_MS = 90000;
const ENGINE_STEP_MS = 3000;

let held = null;

function capture(app) {
  app.once('ready', (_event, launchInfo) => { held = launchInfo === undefined ? null : launchInfo; });
}

function take() {
  const info = held;
  held = null;
  return info;
}

function parseLaunchInfo(info) {
  if (!info || typeof info !== 'object') return null;
  const parts = model.decodeNotificationId(info.identifier);
  if (!parts) return null;
  const hasText = typeof info.userText === 'string' && info.userText.trim() !== '';
  return { ...parts, id: info.identifier, kind: hasText ? 'reply' : 'open', ...(hasText ? { text: info.userText } : {}) };
}

function createColdLaunch(deps) {
  const sleep = deps.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const waitMs = deps.waitMs === undefined ? ENGINE_WAIT_MS : deps.waitMs;
  const stepMs = deps.stepMs === undefined ? ENGINE_STEP_MS : deps.stepMs;
  const now = deps.now || Date.now;

  async function waitForItems() {
    const deadline = now() + waitMs;
    for (;;) {
      const items = await deps.readItems();
      if (items) return items;
      if (now() + stepMs > deadline) return null;
      await sleep(stepMs);
    }
  }

  async function handle(info) {
    const parsed = parseLaunchInfo(info);
    if (!parsed) return { outcome: 'ignored' };
    if (parsed.kind !== 'reply' || deps.coldLockKnown !== true) {
      deps.openApproval(parsed.sessionId);
      return { outcome: 'opened' };
    }
    const stub = { item: { session_id: parsed.sessionId } };
    const items = await waitForItems();
    if (!items) { deps.notice('failed', stub); deps.openApproval(parsed.sessionId); return { outcome: 'failed' }; }
    const item = items.find((i) => i && i.session_id === parsed.sessionId && model.keyFingerprint(i) === parsed.fingerprint);
    if (!item) { deps.removeDelivered(parsed.id); deps.notice('changed', stub); return { outcome: 'stale' }; }
    const key = model.itemKey(item);
    if (!deps.entries.get(key)) deps.makeEntry(key, item);
    const result = await deps.answerer.reply(key, parsed.text);
    deps.removeDelivered(parsed.id);
    if (result.outcome === 'ignored') deps.openApproval(parsed.sessionId);
    return result;
  }

  return { handle };
}

module.exports = { ENGINE_WAIT_MS, ENGINE_STEP_MS, capture, take, parseLaunchInfo, createColdLaunch };
