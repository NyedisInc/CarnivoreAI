
'use strict';

const { act, sub } = require('./items');
const { clip } = require('../strings');
const { waitingRows, ledFor } = require('../need-you');
const rows = require('../session-rows');
const { updateUxFor } = require('../../update-ux');

const DOT = ' · ';
const LOOPBACK = Object.freeze(['127.0.0.1', 'localhost', '::1']);

function phoneWord(phone, t) {
  if (!phone || !phone.effectiveHost) return t('menubar.status.phone_unknown');
  if (LOOPBACK.includes(phone.effectiveHost) || !phone.measuredUrl) return t('menubar.status.this_mac_only');
  return t('menubar.status.phone_reachable');
}

function runningStatus(snap, t) {
  const parts = [snap.server.state === 'running' ? t('menubar.status.running') : snap.server.waitNote || t('menubar.status.starting')];
  const version = snap.server.version || snap.appVersion;
  if (version) parts.push(`v${version}`);
  parts.push(phoneWord(snap.phone, t));
  const side = snap.side || {};
  if (side.beast && side.beast.status === 'ok' && side.beast.data && side.beast.data.enabled) parts.push(t('menubar.status.beast_on'));
  if (side.swarm && side.swarm.status === 'ok' && side.swarm.data && side.swarm.data.enabled) parts.push(t('menubar.status.swarm_on'));
  if (Number.isInteger(snap.server.localServerCount) && snap.server.localServerCount > 0) {
    parts.push(t('menubar.status.local_servers', { count: snap.server.localServerCount }));
  }
  return parts.join(DOT);
}

function needYouItem(snap, env) {
  const list = (snap.listing && Array.isArray(snap.listing.rows) ? snap.listing.rows : []).filter(rows.isRow);
  const waiting = waitingRows(list, env.led);
  if (waiting.length === 0) return null;
  const items = waiting.map(({ info, kind }) => act(`needyou.${rows.rowKey(info)}`, clip(rows.rowLabel(info)), {
    kind: 'session.attention', need: kind, sessionId: info.session.id, tmuxName: info.tmux_session || null,
  }, { sublabel: env.t(kind === 'question' ? 'menubar.need_you.question' : 'menubar.need_you.gate'), led: ledFor(info, env.led) }));
  return sub('needyou', env.t('menubar.need_you', { count: waiting.length }), items,
    { badge: { type: 'alerts', count: waiting.length } });
}

function runningHeader(snap, env) {
  const { t } = env;
  const items = [{ type: 'header', id: 'header', label: t('menubar.header'), sublabel: runningStatus(snap, t), enabled: true }];
  const needYou = needYouItem(snap, env);
  if (needYou) items.push(needYou);
  // could not
  if (snap.setup === 'incomplete') items.push(act('setup.finish', t('menubar.setup.finish'), { kind: 'setup.finish' }));
  return items;
}

function updateRow(snap, t) {
  const ux = updateUxFor(snap.update, snap.autoUpdate === true);
  if (!ux.menuRow) return [];
  return [act('update.install', t('menubar.update.row', { version: ux.menuRow.version }), { kind: 'update.install' }, { icon: 'update' })];
}

function whyText(snap, t) {
  const server = snap.server;
  if (server.portTrust && server.portTrust.trusted === false) {
    return t('menubar.why.port_held', { holder: server.portTrust.holderText || '' });
  }
  if (server.startBlockedReason) return server.startBlockedReason;
  const sup = server.supervisor || {};
  if (sup.gaveUp) return t('menubar.why.gave_up', { count: sup.maxAttempts || 0 });
  if (server.lastExitUnexpected) return t('menubar.why.crashed');
  return t('menubar.why.stopped');
}

function downHeader(snap, env) {
  const { t } = env;
  const off_ = snap.offline || {};
  let tmuxPart;
  if (off_.tmuxRunning === false) tmuxPart = t('menubar.status.tmux_gone');
  else if (Number.isInteger(off_.alive)) tmuxPart = t('menubar.status.agents_alive', { count: off_.alive });
  else tmuxPart = t('menubar.status.agents_unknown');
  const why = whyText(snap, t);
  return [
    { type: 'header', id: 'header', label: t('menubar.header'), sublabel: [t('menubar.status.stopped'), tmuxPart].join(DOT), enabled: true },
    act('server.why', t('menubar.why', { reason: clip(why, 60) }), { kind: 'server.why', detail: why }),
  ];
}

module.exports = { DOT, phoneWord, runningStatus, needYouItem, updateRow, runningHeader, whyText, downHeader };
