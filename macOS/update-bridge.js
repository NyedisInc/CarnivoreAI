
'use strict';

const STATUS_ROUTE = '/api/v1/app-update';
const STATE_ROUTE = '/api/v1/app-update/state';
const PERCENT_STEP = 5;

function createUpdateBridge({ controller, getApi, appVersion, log = () => {} }) {
  let baselineSeq = null;
  let lastSent = null;

  function reportBody() {
    const s = controller.getState();
    return {
      state: s.state,
      current_version: appVersion(),
      latest_version: s.version || '',
      percent: typeof s.percent === 'number' ? s.percent : null,
      detail: s.detail ? String(s.detail).slice(0, 500) : null,
      checked_at: s.checkedAt ? s.checkedAt / 1000 : null,
    };
  }

  function signature(body) {
    const bucket = body.percent === null ? null : Math.floor(body.percent / PERCENT_STEP);
    return JSON.stringify([body.state, body.current_version, body.latest_version, bucket, body.detail]);
  }

  async function push(force = false) {
    const api = getApi();
    if (!api) return;
    const body = reportBody();
    const sig = signature(body);
    if (!force && sig === lastSent) return;
    try {
      const result = await api.sendAuthed(STATE_ROUTE, body, 'POST');
      if (result.reachable) lastSent = sig;
      else log(`[update-bridge] state not accepted: ${result.error}`);
    } catch (err) {
      log(`[update-bridge] state push failed: ${err && err.message}`);
    }
  }

  async function onServerStatus(result) {
    if (!result || result.status !== 'ok' || !result.data) return;
    const { command_seq: seq, command, attached, state } = result.data;
    if (typeof seq !== 'number') return;
    if (baselineSeq === null) {
      baselineSeq = seq;
    } else if (seq > baselineSeq) {
      baselineSeq = seq;
      log(`[update-bridge] command ${command} (#${seq})`);
      if (command === 'check') await controller.check();
      else if (command === 'install') await controller.install();
      else if (command === 'config') controller.applyAutoUpdate();
    }
    await push(!attached || state !== controller.getState().state);
  }

  return { push, onServerStatus, reportBody };
}

module.exports = { STATUS_ROUTE, STATE_ROUTE, PERCENT_STEP, createUpdateBridge };
