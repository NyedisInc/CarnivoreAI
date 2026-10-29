// Keep Mac Awake

'use strict';

const { act, off, maybe, sub, sep, check } = require('./items');
const trayAutomations = require('../../tray-automations');

function sideReason(res, t) {
  if (!res || res.status === 'unknown') return t('menubar.reason.unread');
  if (res.status === 'missing') return t('menubar.reason.newer_server');
  return null;
}

/* Keep Mac Awake */
function keepAwakeItem(snap, env) {
  const { t } = env;
  const res = (snap.side || {}).keepAwake;
  const reason = sideReason(res, t);
  if (reason) return off('keep_awake', t('menubar.keep_awake'), reason);
  const always = Boolean(res.data && res.data.always);
  return check('keep_awake', t('menubar.keep_awake'), always, { kind: 'autonomy.keep_awake', always: !always });
}

function automationRows(auto, env) {
  const { t } = env;
  const open = act('automations.open', t('menubar.automations.open'), { kind: 'app.open', hash: trayAutomations.AUTOMATIONS_HASH });
  if (!auto || !auto.reachable) return [off('automations.unread', t('menubar.automations'), t('menubar.reason.unread')), open];
  const items = [off('automations.next', t(auto.paused ? 'menubar.automations.next_held' : 'menubar.automations.next'))];
  if (auto.upcoming.length === 0) items.push(off('automations.next.none', t('menubar.automations.none_scheduled')));
  for (const run of auto.upcoming) {
    items.push(off(`automations.next.${run.name}.${run.at}`, run.name, trayAutomations.whenText(run.at, env.now)));
  }
  items.push(off('automations.last', t('menubar.automations.last')));
  if (auto.recent.length === 0) items.push(off('automations.last.none', t('menubar.automations.no_runs')));
  for (const run of auto.recent) items.push(off(`automations.last.${run.name}.${run.at}`, run.name, run.status));
  items.push(open);
  return items;
}

function autonomyMenu(snap, env) {
  const { t } = env;
  const side = snap.side || {};
  const beast = side.beast;
  const beastReason = sideReason(beast, t) || (beast.data && beast.data.available === false ? t('menubar.reason.beast_plugin_off') : null);
  const beastOn = Boolean(beast && beast.data && beast.data.enabled);
  const swarm = side.swarm;
  const swarmOn = Boolean(swarm && swarm.data && swarm.data.enabled);
  const auto = side.automations;
  const items = [
    beastReason ? off('beast', t('menubar.autonomy.beast'), beastReason)
      : check('beast', t('menubar.autonomy.beast'), beastOn, beastOn ? { kind: 'autonomy.beast_off' } : { kind: 'autonomy.beast_open' },
        { sublabel: t(beastOn ? 'menubar.autonomy.beast_on_hint' : 'menubar.autonomy.beast_off_hint') }),
    sideReason(swarm, t) ? off('swarm', t('menubar.autonomy.swarm'), sideReason(swarm, t))
      : check('swarm', t('menubar.autonomy.swarm'), swarmOn, { kind: 'autonomy.swarm', enabled: !swarmOn }),
    auto && auto.reachable
      ? check('scheduler', t('menubar.autonomy.pause_scheduler'), auto.paused, { kind: 'autonomy.scheduler', paused: !auto.paused })
      : off('scheduler', t('menubar.autonomy.pause_scheduler'), t('menubar.reason.unread')),
    maybe(snap.routes.standDown !== 'missing', 'stand_down', t('menubar.autonomy.stand_down'), { kind: 'autonomy.stand_down' },
      t('menubar.reason.newer_server'), { sublabel: t('menubar.autonomy.stand_down_hint') }),
    sep(),
    ...automationRows(auto, { t, now: snap.now }),
  ];
  return sub('autonomy', t('menubar.autonomy'), items);
}

module.exports = { sideReason, keepAwakeItem, automationRows, autonomyMenu };
