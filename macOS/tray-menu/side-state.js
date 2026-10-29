
'use strict';

const trayAutomations = require('../tray-automations');
const trayTerminal = require('../tray-terminal');

const ROUTES = Object.freeze({
  beast: '/api/v1/beast-mode',
  swarm: '/api/v1/swarm/switch',
  keepAwake: '/api/v1/system/keep-awake',
  standDown: '/api/v1/autonomy/stand-down',
  logLevel: '/api/v1/log-level',
  diagnostics: '/api/v1/diagnostics',
  account: '/api/v1/catalog/auth/session',
  appUpdate: '/api/v1/app-update',
  preferences: '/api/v1/preferences',
});

const RESOURCES = Object.freeze({
  beast: Object.freeze(['beast_mode']),
  swarm: Object.freeze(['swarm_switch']),
  keepAwake: Object.freeze(['keep_awake', 'auto_sleep']),
  automations: Object.freeze(['automations', 'automation_runs']),
  sysop: Object.freeze(['swarm_roster']),
  logLevel: Object.freeze([]),
  account: Object.freeze([]),
  appUpdate: Object.freeze(['app_update']),
  desktopPrefs: Object.freeze(['desktop_preferences']),
});

const DEBUG_EXPIRES_IN_S = 1800;

function classify(result) {
  if (result && result.reachable) return { status: 'ok', data: result.data, error: null };
  if (result && (result.status === 404 || result.status === 405)) return { status: 'missing', data: null, error: null };
  return { status: 'unknown', data: null, error: (result && result.error) || 'not read' };
}

function emptySide() {
  const unknown = { status: 'unknown', data: null, error: 'not read yet' };
  return { beast: unknown, swarm: unknown, keepAwake: unknown, logLevel: unknown, automations: null, account: null, appUpdate: unknown, desktopPrefs: unknown };
}

const READERS = Object.freeze({
  beast: async (api) => classify(await api.getAuthed(ROUTES.beast)),
  swarm: async (api) => classify(await api.getAuthed(ROUTES.swarm)),
  keepAwake: async (api) => classify(await api.getAuthed(ROUTES.keepAwake)),
  logLevel: async (api) => classify(await api.getAuthed(ROUTES.logLevel)),
  automations: (api) => trayAutomations.fetchAutomationsSnapshot(api),
  sysop: (api) => trayTerminal.refreshSysop(api),
  appUpdate: async (api) => classify(await api.getAuthed(ROUTES.appUpdate)),
  desktopPrefs: async (api) => classify(await api.getAuthed(ROUTES.preferences)),
  account: async (api) => {
    const result = await api.getAuthed(ROUTES.account);
    const acct = result.reachable && result.data;
    return acct && acct.signed_in && acct.login ? String(acct.login) : null;
  },
});

async function readSide(api, names, current) {
  const values = await Promise.all(names.map((name) => READERS[name](api)));
  const next = { ...current };
  names.forEach((name, i) => { if (name !== 'sysop') next[name] = values[i]; });
  return next;
}

function resourcesForTopics(topics) {
  const fired = new Set(topics || []);
  return Object.keys(RESOURCES).filter((name) => RESOURCES[name].some((t) => fired.has(t)));
}

function isPushed(name, pushed) {
  return Boolean(pushed) && RESOURCES[name].some((t) => pushed.has(t));
}

function pollable(pushed) {
  return Object.keys(RESOURCES).filter((name) => RESOURCES[name].length > 0 && !isPushed(name, pushed));
}

function onOpenReads(pushed) {
  return Object.keys(RESOURCES).filter((name) => !isPushed(name, pushed));
}

function logLevelBody(level) {
  return level === 'debug' ? { level, expires_in_s: DEBUG_EXPIRES_IN_S } : { level };
}

module.exports = {
  ROUTES, RESOURCES, DEBUG_EXPIRES_IN_S, classify, emptySide, readSide, resourcesForTopics, isPushed, pollable,
  onOpenReads, logLevelBody,
};
