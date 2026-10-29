
'use strict';

const model = require('./model');

const SOURCE = 'owner_banner';

function createAnswerer(deps) {
  const route = (sessionId, tail) => `/api/v1/sessions/${encodeURIComponent(sessionId)}/dialog/${tail}`;

  function settle(entry, result) {
    entry.done = true;
    deps.closeBanner(entry);
    if (result && result.reachable) return { outcome: 'answered' };
    entry.held = [];
    const status = result && typeof result.status === 'number' ? result.status : undefined;
    deps.notice(status === 409 ? 'changed' : 'failed', entry);
    return { outcome: status === 409 ? 'stale' : 'failed', status };
  }

  async function press(actionId) {
    const parts = model.decodeActionId(actionId);
    if (!parts) return { outcome: 'ignored' };
    const entry = deps.entries.get(`${parts.sessionId}|${parts.fingerprint}`);
    if (!entry || entry.busy || entry.done || entry.step !== parts.step) return { outcome: 'ignored' };
    const button = entry.plan.buttons[parts.index];
    if (!button) return { outcome: 'ignored' };
    if (button.kind === 'open_app' || (deps.isLocked && deps.isLocked())) {
      entry.done = true;
      deps.closeBanner(entry);
      deps.openApproval(entry.item.session_id);
      return { outcome: button.kind === 'open_app' ? 'opened' : 'locked' };
    }
    const label = model.optionLabel(entry.item, entry.step, button.optionIndex);
    if (label === null) return { outcome: 'ignored' };
    entry.busy = true;
    try {
      if (entry.plan.mode === 'ask') {
        entry.held.push(label);
        if (entry.step + 1 < entry.plan.total) {
          entry.step += 1;
          deps.showStep(entry);
          return { outcome: 'next' };
        }
        const answers = entry.held.map((option) => ({ option }));
        const body = { questions_fingerprint: entry.item.questions_fingerprint, answers, source: SOURCE };
        return settle(entry, await write(route(entry.item.session_id, 'answer-all'), body));
      }
      const body = { fingerprint: entry.item.fingerprint, choice: { option: label }, source: SOURCE };
      return settle(entry, await write(route(entry.item.session_id, 'answer'), body));
    } finally {
      entry.busy = false;
    }
  }

  async function reply(key, text) {
    const entry = deps.entries.get(key);
    if (!entry || entry.busy || entry.done || !entry.plan || entry.plan.reply !== true || entry.step !== 0) return { outcome: 'ignored' };
    if (deps.isLocked && deps.isLocked()) {
      entry.done = true;
      deps.closeBanner(entry);
      deps.openApproval(entry.item.session_id);
      return { outcome: 'locked' };
    }
    const typed = typeof text === 'string' ? text.trim() : '';
    if (typed === '') { deps.showStep(entry); return { outcome: 'ignored' }; }
    if (/[\u0000-\u001f\u007f]/.test(typed)) {
      deps.notice('bad_chars', entry);
      deps.showStep(entry);
      return { outcome: 'bad_chars' };
    }
    if ([...typed].length > model.MAX_REPLY) {
      deps.notice('too_long', entry);
      deps.showStep(entry);
      return { outcome: 'too_long' };
    }
    entry.busy = true;
    try {
      const body = { fingerprint: entry.item.fingerprint, choice: { other: typed }, source: SOURCE };
      return settle(entry, await write(route(entry.item.session_id, 'answer'), body));
    } finally {
      entry.busy = false;
    }
  }

  async function write(path, body) {
    const api = deps.getApi();
    if (!api) return { reachable: false, data: null, error: 'the server is not reachable' };
    try {
      return await api.sendAuthed(path, body, 'POST');
    } catch (error) {
      return { reachable: false, data: null, error: String((error && error.message) || error) };
    }
  }

  return { press, reply };
}

module.exports = { SOURCE, createAnswerer };
