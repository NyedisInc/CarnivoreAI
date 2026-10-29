
'use strict';

const { act, off, maybe, sub, sep, tidy } = require('./items');
const { clip } = require('../strings');
const { needYouKind, ledFor } = require('../need-you');
const rows = require('../session-rows');

const PEER_HASH = '#pack/computers';

const RECENT_LOCAL = 8;

function statusWord(info, need, t) {
  if (need) return t(need === 'question' ? 'menubar.need_you.question' : 'menubar.need_you.gate');
  const known = ['working', 'working_subagent', 'idle', 'asleep', 'dead', 'notice', 'finished_unread'];
  const status = known.includes(info.activity_status) ? info.activity_status : 'unknown';
  return t(`menubar.session.status.${status}`);
}

function sessionRow(info, need, t, led) {
  const key = rows.rowKey(info);
  const block = rows.terminalBlock(info);
  const reason = block ? t(block) : null;
  const target = { tmuxName: info.tmux_session || null, sessionId: info.session.id };
  const term = (mode) => ({ kind: 'session.terminal', mode, ...target, folder: rows.rowFolder(info), label: rows.rowLabel(info) });
  const items = [
    act(`${key}.open`, t('menubar.session.open_in_app'), { kind: 'session.open', ...target }),
    maybe(!block, `${key}.watch`, t('menubar.session.watch'), term('watch'), reason),
    maybe(!block, `${key}.type`, t('menubar.session.type'), term('type'), reason),
    maybe(!block, `${key}.copy`, t('menubar.session.copy_attach'), { kind: 'session.copy_attach', ...target }, reason),
    sep(),
    act(`${key}.restart`, t('menubar.session.restart'), { kind: 'session.restart', ...target },
      { sublabel: t('menubar.session.restart_hint') }),
  ];
  return sub(`session.${key}`, clip(rows.rowLabel(info)), items, { sublabel: statusWord(info, need, t), led: ledFor(info, led) });
}

function terminalShortcuts(snap, t) {
  const sysop = snap.sysop || {};
  return [
    act('terminal.sysop', t('menubar.terminal.sysop'), { kind: 'terminal.sysop' },
      { sublabel: t(sysop.tmuxName ? 'menubar.terminal.sysop_attach' : 'menubar.terminal.sysop_plain') }),
    act('terminal.shell', t('menubar.terminal.shell'), { kind: 'terminal.shell' }, { sublabel: t('menubar.terminal.shell_hint') }),
  ];
}

function sessionsMenu(snap, env) {
  const { t } = env;
  const listing = snap.listing || {};
  const tail = [sep(), ...terminalShortcuts(snap, t), sep(),
    act('sessions.all', t('menubar.sessions.all'), { kind: 'app.open', hash: '#sessions' })];
  if (snap.setup === 'incomplete') {
    return sub('sessions', t('menubar.sessions'), tidy([off('sessions.setup', t('menubar.sessions.setup_pending')), ...tail]));
  }
  if (!listing.reachable || !Array.isArray(listing.rows)) {
    return sub('sessions', t('menubar.sessions'), tidy([off('sessions.unread', t('menubar.sessions.unreadable'), listing.error || null), ...tail]));
  }
  const all = listing.rows.filter(rows.isRow);
  const tagged = all.map((info) => ({ info, need: needYouKind(info, env.led) }));
  const needing = tagged.filter((r) => r.need);
  const recent = tagged.filter((r) => !r.need && rows.isLocal(r.info))
    .sort((a, b) => rows.recency(b.info) - rows.recency(a.info)).slice(0, RECENT_LOCAL);
  const peers = new Map();
  for (const { info } of tagged) {
    if (rows.isLocal(info)) continue;
    const host = info.host_key || 'peer';
    const entry = peers.get(host) || { label: info.host_label || host, count: 0 };
    entry.count += 1;
    peers.set(host, entry);
  }
  const items = [
    ...needing.map((r) => sessionRow(r.info, r.need, t, env.led)),
    ...recent.map((r) => sessionRow(r.info, null, t, env.led)),
  ];
  if (items.length === 0) items.push(off('sessions.none', t('menubar.sessions.none')));
  if (peers.size) items.push(sep());
  for (const [host, entry] of peers) {
    items.push(act(`peer.${host}`, clip(entry.label), { kind: 'app.open', hash: PEER_HASH },
      { sublabel: t('menubar.sessions.peer_count', { count: entry.count }) }));
  }
  return sub('sessions', t('menubar.sessions.count', { count: all.length }), tidy([...items, ...tail]));
}

module.exports = { PEER_HASH, RECENT_LOCAL, statusWord, sessionRow, terminalShortcuts, sessionsMenu };
