
'use strict';

const scripts = require('../terminal-scripts');

const LOCAL_HOST_KEY = 'local';

function isRow(info) {
  return Boolean(info && info.session && typeof info.session.id === 'string' && info.session.id);
}

function rowKey(info) {
  if (typeof info.session_uuid === 'string' && info.session_uuid) return `uuid:${info.session_uuid}`;
  if (Number.isInteger(info.session_row_id)) return `row:${info.session_row_id}`;
  return `id:${info.session.id}`;
}

function isLocal(info) {
  return (info.host_key || LOCAL_HOST_KEY) === LOCAL_HOST_KEY && !info.session.id.startsWith('remote:');
}

function rowLabel(info) {
  return info.label || info.tmux_session || info.session.id;
}

function recency(info) {
  const at = Date.parse(info.session.last_activity || '');
  return Number.isFinite(at) ? at : 0;
}

/* cannot be opened */
function terminalBlock(info) {
  if (!isLocal(info)) return 'menubar.reason.peer';
  if (info.activity_status === 'asleep') return 'menubar.reason.asleep';
  if (info.activity_status === 'dead' || info.activity_status === 'stopped') return 'menubar.reason.dead';
  if (!scripts.isValidTmuxName(info.tmux_session)) return 'menubar.reason.no_tmux';
  return null;
}

function rowFolder(info) {
  return scripts.isAbsolutePath(info.session.working_dir) ? info.session.working_dir : null;
}

module.exports = { LOCAL_HOST_KEY, isRow, rowKey, isLocal, rowLabel, recency, terminalBlock, rowFolder };
