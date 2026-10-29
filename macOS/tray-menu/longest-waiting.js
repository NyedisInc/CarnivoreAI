
'use strict';

const { needYouKind } = require('./need-you');
const rows = require('./session-rows');

function longestWaiting(list, led) {
  if (!Array.isArray(list) || !led) return null;
  let best = null;
  for (const info of list) {
    if (!rows.isRow(info) || !rows.isLocal(info)) continue;
    const need = needYouKind(info, led);
    if (!need) continue;
    const since = rows.recency(info);
    if (best === null || since < best.since) best = { since, need, sessionId: info.session.id, tmuxName: info.tmux_session || null };
  }
  return best === null ? null : { need: best.need, sessionId: best.sessionId, tmuxName: best.tmuxName };
}

module.exports = { longestWaiting };
