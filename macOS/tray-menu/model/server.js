
'use strict';

const { act, off, maybe, sub, sep, check, radio, tidy } = require('./items');
const { terminalShortcuts } = require('./sessions');

const LOG_LEVELS = Object.freeze(['error', 'warn', 'info', 'debug']);

function supervisorRows(snap, t) {
  const s = snap.server.supervisor;
  if (!s || (!s.gaveUp && !s.pending && !s.attempts)) return [];
  const params = { count: s.attempts || 0, max: s.maxAttempts || 0 };
  const key = s.gaveUp ? 'menubar.supervisor.gave_up' : s.pending ? 'menubar.supervisor.restarting' : 'menubar.supervisor.restarted';
  const label = t(key, params);
  return [
    off('supervisor.state', label),
    act('supervisor.why', t('menubar.supervisor.why'), { kind: 'server.supervisor_why', label, detail: s.message || '', gaveUp: Boolean(s.gaveUp) }),
    sep(),
  ];
}

function setupLabel(snap, t) {
  if (snap.joined) return snap.mainLabel ? t('menubar.setup.joined_named', { name: snap.mainLabel }) : t('menubar.setup.joined');
  if (snap.setup === 'incomplete') return t('menubar.setup.incomplete');
  if (snap.setup === 'complete') return t('menubar.setup.config');
  return t('menubar.setup.unknown');
}

function setupHint(snap, t) {
  if (snap.joined) return undefined;
  if (snap.setup === 'incomplete') return { sublabel: t('menubar.setup.incomplete_hint') };
  if (snap.setup !== 'complete') return { sublabel: t('menubar.setup.unknown_hint') };
  return undefined;
}

function uninstallMenu(t) {
  return sub('uninstall', t('menubar.uninstall'), [
    act('uninstall.app', t('menubar.uninstall.app'), { kind: 'server.uninstall' }),
    act('uninstall.nuke', t('menubar.uninstall.nuke'), { kind: 'server.nuke' }),
  ]);
}

function serverMenuRunning(snap, env) {
  const { t } = env;
  const running = snap.server.state === 'running';
  const needs = t('menubar.reason.needs_server');
  return sub('server', t('menubar.server'), tidy([
    ...supervisorRows(snap, t),
    maybe(running, 'server.restart', t('menubar.server.restart'), { kind: 'server.restart' }, needs),
    act('server.stop', t('menubar.server.stop'), { kind: 'server.stop' }),
    sep(),
    maybe(running, 'server.logs', t('menubar.server.logs'), { kind: 'app.open', hash: '#logs' }, needs),
    act('server.tail_log', t('menubar.server.tail_log'), { kind: 'server.tail_log' }),
    act('server.console_log', t('menubar.server.console_log'), { kind: 'server.console_log' }),
    act('server.reveal_logs', t('menubar.server.reveal_logs'), { kind: 'server.reveal_logs' }),
    act('server.diagnostics', t('menubar.server.copy_diagnostics'), { kind: 'server.copy_diagnostics' }),
    act('server.export_diagnostics', t('menubar.server.export_diagnostics'), { kind: 'server.export_diagnostics' }),
    act('server.health', t('menubar.server.check_health'), { kind: 'server.check_health' }),
    act('server.edit_config', t('menubar.server.edit_config'), { kind: 'server.edit_config' }),
    sep(),
    act('setup.wizard', setupLabel(snap, t), { kind: 'setup.wizard' }, setupHint(snap, t)),
    maybe(running, 'server.cli', t('menubar.server.cli'), { kind: 'app.open', hash: '#settings/terminal' }, needs),
    check('server.login', t('menubar.server.launch_at_login'), snap.launchAtLogin, { kind: 'server.toggle_login' }),
    sep(),
    uninstallMenu(t),
  ]));
}

function serverMenuDown(snap, env) {
  const { t } = env;
  const trust = snap.server.portTrust;
  const holder = snap.server.portHolder || (trust && trust.trusted === false ? trust.holderText : null);
  return sub('server', t('menubar.server'), tidy([
    ...supervisorRows(snap, t),
    act('server.start_debug', t('menubar.server.start_debug'), { kind: 'server.start_debug' }, { sublabel: t('menubar.server.start_debug_hint') }),
    act('server.reveal_logs', t('menubar.server.reveal_logs'), { kind: 'server.reveal_logs' }),
    act('server.edit_config', t('menubar.server.edit_config'), { kind: 'server.edit_config' }),
    maybe(Boolean(holder), 'server.kill_port', t('menubar.server.kill_port'), { kind: 'server.kill_port_holder' },
      t('menubar.server.port_free'), { sublabel: holder || undefined }),
    act('server.reinstall', t('menubar.server.reinstall_env'), { kind: 'server.reinstall_env' }),
    act('server.crash', t('menubar.server.crash_report'), { kind: 'server.crash_report' }),
    check('server.login', t('menubar.server.launch_at_login'), snap.launchAtLogin, { kind: 'server.toggle_login' }),
    sep(),
    ...terminalShortcuts(snap, t),
    sep(),
    uninstallMenu(t),
  ]).map((item) => { if (item.sublabel === undefined) delete item.sublabel; return item; }));
}

function debugMenu(snap, env) {
  const { t } = env;
  const res = (snap.side || {}).logLevel;
  const up = snap.server.state === 'running';
  const items = [];
  if (!up) items.push(off('debug.level', t('menubar.debug.log_level'), t('menubar.reason.needs_server')));
  else if (!res || res.status !== 'ok') {
    items.push(off('debug.level', t('menubar.debug.log_level'),
      t(res && res.status === 'missing' ? 'menubar.reason.newer_server' : 'menubar.reason.unread')));
  } else {
    items.push(off('debug.level', t('menubar.debug.log_level')));
    const current = res.data && res.data.level;
    for (const level of LOG_LEVELS) {
      const extra = level === 'debug' ? { sublabel: t('menubar.debug.debug_expires') } : undefined;
      if (level === 'debug' && snap.routes.logLevelExpiry === 'missing') {
        items.push(off(`debug.level.${level}`, t(`menubar.debug.level.${level}`), t('menubar.reason.newer_server')));
      } else {
        items.push(radio(`debug.level.${level}`, t(`menubar.debug.level.${level}`), current === level, { kind: 'debug.log_level', level }, extra));
      }
    }
  }
  items.push(sep(), act('debug.state_dir', t('menubar.debug.reveal_state'), { kind: 'debug.reveal_state' }));
  return sub('debug', t('menubar.debug'), items);
}

module.exports = { LOG_LEVELS, supervisorRows, setupLabel, setupHint, serverMenuRunning, serverMenuDown, debugMenu };
