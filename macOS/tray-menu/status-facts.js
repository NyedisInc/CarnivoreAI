
'use strict';

const { isServerUp } = require('./model');

const BUTTON_IDS = Object.freeze(['server.start', 'terminal.offline', 'server.console_log', 'server.diagnostics']);
const RUNNABLE_IDS = Object.freeze([...BUTTON_IDS, 'server.why']);

function findItem(items, id) {
  return items.find((item) => item.id === id);
}

function statusFacts(snap, items, t) {
  if (isServerUp(snap)) return null;
  const header = findItem(items, 'header') || {};
  const why = findItem(items, 'server.why') || {};
  return {
    windowTitle: t('menubar.status_window.window_title'),
    title: t('menubar.status_window.title'),
    status: header.sublabel || '',
    why: { text: why.label || '', enabled: why.enabled !== false && Boolean(why.action), hint: t('menubar.status_window.why_hint') },
    buttons: BUTTON_IDS.map((id) => findItem(items, id)).filter(Boolean).map((item) => ({
      id: item.id, label: item.label, enabled: item.enabled !== false && Boolean(item.action), reason: item.enabled === false ? item.sublabel || null : null,
    })),
  };
}

function actionForClick(items, id) {
  if (typeof id !== 'string' || !RUNNABLE_IDS.includes(id)) return null;
  const item = findItem(items, id);
  return item && item.enabled !== false && item.action ? item.action : null;
}

module.exports = { BUTTON_IDS, RUNNABLE_IDS, statusFacts, actionForClick };
