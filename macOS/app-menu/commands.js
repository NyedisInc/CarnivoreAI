
'use strict';

const { sessionLink } = require('../tray-menu/actions/sessions');

const MENU_VERBS = Object.freeze([
  'file.new_session', 'file.open_project', 'session.restart', 'session.stop', 'session.rename', 'session.open_in',
  'session.reveal', 'session.open_editor', 'file.reveal_project', 'file.open_project_editor',
]);

const MAIN_ACTIONS = Object.freeze([
  'carnivore.about', 'carnivore.settings', 'carnivore.quit_engine', 'file.new_window', 'session.answer', 'help.docs', 'help.export_diagnostics',
]);

const HELP_URL = 'https://carnivore.ai/help';

function sendVerb(appWindow, verb) {
  if (typeof verb !== 'string' || !MENU_VERBS.includes(verb)) return false;
  return appWindow.sendMenuCommand(verb) === true;
}

function answerWaiting(appWindow, waiting) {
  const target = waiting();
  if (!target) return false;
  return target.need === 'question' ? appWindow.openApproval(target.sessionId) : appWindow.open(sessionLink(target));
}

module.exports = { MENU_VERBS, MAIN_ACTIONS, HELP_URL, sendVerb, answerWaiting };
