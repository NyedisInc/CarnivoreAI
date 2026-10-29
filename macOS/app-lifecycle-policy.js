'use strict';

const { LOGIN_LAUNCH_ARG, isLoginLaunch, handleSecondInstance } = require('./second-instance');

const ENGINE_SURVIVES_CMDQ = true;

const QUIT_INTENTS = Object.freeze(['app', 'engine']);

function launchDecision({ argv, windowAtLogin, firstRunNeedsWindow = false, startBlocked = false }) {
  const loginLaunch = isLoginLaunch(argv);
  return { loginLaunch, openWindow: startBlocked !== true && (!loginLaunch || windowAtLogin === true || firstRunNeedsWindow === true) };
}

function quitPlan({ intent, noticeShown, engineSurvivesQuit, systemQuit = false }) {
  const engine = intent === 'engine';
  return {
    stopEngine: engine || engineSurvivesQuit !== true,
    showNotice: !engine && noticeShown !== true && systemQuit !== true,
  };
}

function windowCloseDecision({ platform }) {
  void platform;
  return { quitApp: false };
}

function dockClickOrder({ windowOpen, serverRunning, statusWindowAvailable, trayAvailable }) {
  const steps = [];
  if (windowOpen) steps.push('raise');
  if (serverRunning) steps.push('open-window');
  else if (statusWindowAvailable) steps.push('open-status');
  if (trayAvailable) steps.push('tray-menu');
  return steps.length ? steps : ['nothing'];
}

function dockClickDecision(input) {
  return dockClickOrder(input)[0];
}

function secondInstanceDecision(argv) {
  return handleSecondInstance(argv);
}

function menuBarIconWanted(value) {
  return value !== false;
}

function trayPresenceDecision({ wanted, hasTray }) {
  const want = menuBarIconWanted(wanted);
  if (want && !hasTray) return 'create';
  if (!want && hasTray) return 'destroy';
  return 'keep';
}

module.exports = {
  LOGIN_LAUNCH_ARG, ENGINE_SURVIVES_CMDQ, QUIT_INTENTS,
  launchDecision, quitPlan, windowCloseDecision, dockClickOrder, dockClickDecision, secondInstanceDecision,
  menuBarIconWanted, trayPresenceDecision,
};
