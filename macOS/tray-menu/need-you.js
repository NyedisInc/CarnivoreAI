
'use strict';

const path = require('path');

const NEED_YOU_INNER = Object.freeze({ 'waiting-permission': 'question', 'waiting-input': 'gate' });

function loadStatusLed(clientDir) {
  return require(path.join(clientDir, 'js', 'status-led.js'));
}

function ledFor(info, led) {
  if (!info || !led) return null;
  return led.ledStateFor({
    activity_status: info.activity_status,
    unread: info.unread,
    startup_gate: info.startup_gate,
    host_offline: led.hostOffline ? led.hostOffline(info) : null,
    usage_limit: led.usageLimitLabel ? led.usageLimitLabel(info) : null,
  });
}

function needYouKind(info, led) {
  const state = ledFor(info, led);
  return NEED_YOU_INNER[state && state.inner] || null;
}

function waitingRows(rows, led) {
  return (Array.isArray(rows) ? rows : []).filter((info) => info && typeof info === 'object')
    .map((info) => ({ info, kind: needYouKind(info, led) })).filter((w) => w.kind);
}

function needYouCount(rows, led) {
  return waitingRows(rows, led).length;
}

module.exports = { NEED_YOU_INNER, loadStatusLed, ledFor, needYouKind, waitingRows, needYouCount };
