
'use strict';

const { act, maybe, sep } = require('./items');

const UPDATE_STATES = Object.freeze(['not_configured', 'invalid_feed', 'idle', 'checking', 'available', 'downloading', 'ready', 'current', 'unknown', 'error', 'update_refused']);

function footer(snap, env) {
  const { t } = env;
  const up = snap.server.state === 'running';
  const update = snap.update || { state: 'idle' };
  const state = UPDATE_STATES.includes(update.state) ? update.state : 'idle';
  const account = snap.side && snap.side.account;
  const settingsExtra = { accelerator: 'CommandOrControl+,' };
  if (account) settingsExtra.sublabel = t('menubar.settings.signed_in', { login: account.split('@')[0] });
  return [
    sep(),
    // could not be read
    up && !account ? act('account.sign_in', t('menubar.account.sign_in'), { kind: 'app.account' }) : null,
    maybe(up, 'settings', t('menubar.settings'), { kind: 'app.open', hash: '#settings' }, t('menubar.reason.needs_server'), settingsExtra),
    act('update.check', t('menubar.update.check'), { kind: 'update.check' }, {
      sublabel: t(`menubar.update.state.${state}`, { version: update.version || '', percent: update.percent || 0, detail: update.detail || '' }),
    }),
    act('about', t('menubar.about'), { kind: 'app.about' }),
    act('quit', t('menubar.quit'), { kind: 'app.quit' }, { accelerator: 'CommandOrControl+Q', sublabel: t('menubar.quit_hint') }),
    act('quit_stop', t('menubar.quit_stop'), { kind: 'app.quit_stop' }, { sublabel: t('menubar.quit_stop_hint') }),
  ];
}

module.exports = { UPDATE_STATES, footer };
