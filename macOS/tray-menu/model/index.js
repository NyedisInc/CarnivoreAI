
'use strict';

const { act, off, maybe, sep, tidy } = require('./items');
const header = require('./header');
const { sessionsMenu } = require('./sessions');
const { phoneMenu } = require('./phone');
const { keepAwakeItem, autonomyMenu } = require('./autonomy');
const server = require('./server');
const { footer } = require('./footer');

function isServerUp(snap) {
  const trust = snap.server.portTrust;
  return snap.server.state !== 'stopped' && !(trust && trust.trusted === false);
}

function runningLayout(snap, env) {
  const { t } = env;
  return [
    ...header.updateRow(snap, t),
    ...header.runningHeader(snap, env),
    act('app.open', t('menubar.open_carnivore'), { kind: 'app.open', hash: '' }),
    sessionsMenu(snap, env),
    act('session.new', t('menubar.new_session'), { kind: 'app.open', hash: '' }, { sublabel: t('menubar.new_session_hint') }),
    sep(),
    phoneMenu(snap, env),
    keepAwakeItem(snap, env),
    autonomyMenu(snap, env),
    sep(),
    server.serverMenuRunning(snap, env),
    act('browser', t('menubar.open_in_browser'), { kind: 'app.browser' }),
  ];
}

function downLayout(snap, env) {
  const { t } = env;
  const restart = snap.server.supervisor && snap.server.supervisor.gaveUp;
  // Kill Port Holder
  const portBusy = Boolean(snap.server.portTrust && snap.server.portTrust.trusted === false);
  return [
    ...header.updateRow(snap, t),
    ...header.downHeader(snap, env),
    maybe(!portBusy, 'server.start', t(restart ? 'menubar.server.restart' : 'menubar.server.start'), { kind: 'server.start' },
      t('menubar.reason.port_in_use')),
    ...(snap.server.supervisor && snap.server.supervisor.slowRetry
      ? [act('server.stop_retry', t('menubar.server.stop_retry'), { kind: 'server.stop_retry' })] : []),
    snap.offlineTuiAvailable
      ? act('terminal.offline', t('menubar.terminal.offline'), { kind: 'terminal.offline' }, { sublabel: t('menubar.terminal.offline_hint') })
      : off('terminal.offline', t('menubar.terminal.offline'), t('menubar.reason.no_offline_tui')),
    act('server.console_log', t('menubar.server.console_log'), { kind: 'server.console_log' }),
    act('server.diagnostics', t('menubar.server.copy_diagnostics'), { kind: 'server.copy_diagnostics' }),
    act('server.export_diagnostics', t('menubar.server.export_diagnostics'), { kind: 'server.export_diagnostics' }),
    sep(),
    server.serverMenuDown(snap, env),
  ];
}

function buildMenuModel(snap, env) {
  const body = isServerUp(snap) ? runningLayout(snap, env) : downLayout(snap, env);
  const debug = snap.optionKey ? [sep(), server.debugMenu(snap, env)] : [];
  return tidy([...body, ...debug, ...footer(snap, env)]);
}

module.exports = { isServerUp, runningLayout, downLayout, buildMenuModel };
