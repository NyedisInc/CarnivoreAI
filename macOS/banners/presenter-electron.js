
'use strict';

const MAX_NOTICES = 20;

function actionIndexOf(args) {
  const details = args[0];
  if (details && typeof details === 'object' && Number.isInteger(details.actionIndex)) return details.actionIndex;
  return Number.isInteger(args[1]) ? args[1] : null;
}

function replyTextOf(args) {
  const details = args[0];
  if (details && typeof details === 'object' && typeof details.reply === 'string') return details.reply;
  return typeof args[1] === 'string' ? args[1] : null;
}

function createPresenter(deps) {
  const { Notification } = deps;
  const live = new Map();
  const notices = new Set();

  const forget = (key, notification) => { if (live.get(key) === notification) live.delete(key); };

  function show(key, plan, actionIds) {
    close(key);
    const options = { title: plan.title, body: plan.body };
    if (plan.id) options.id = plan.id;
    if (plan.groupId) options.groupId = plan.groupId;
    if (plan.reply === true) { options.hasReply = true; options.replyPlaceholder = plan.replyPlaceholder || ''; }
    if (plan.buttons.length) options.actions = plan.buttons.map((b) => ({ type: 'button', text: b.label }));
    const notification = new Notification(options);
    notification.on('action', (...args) => {
      const index = actionIndexOf(args);
      const id = index === null ? undefined : actionIds[index];
      if (id) deps.onAction(id);
    });
    notification.on('reply', (...args) => {
      const text = replyTextOf(args);
      if (text !== null && deps.onReply) deps.onReply(key, text);
    });
    notification.on('click', () => deps.onClick(key));
    notification.on('close', () => forget(key, notification));
    notification.on('failed', (_event, error) => {
      if (deps.onFailed) deps.onFailed(key, error);
    });
    live.set(key, notification);
    notification.show();
  }

  function close(key) {
    const notification = live.get(key);
    if (!notification) return;
    live.delete(key);
    notification.close();
  }

  function removeDelivered(id) {
    if (typeof Notification.remove === 'function') Notification.remove(id);
  }

  async function deliveredIds() {
    if (typeof Notification.getHistory !== 'function') return [];
    try {
      return (await Notification.getHistory()).map((n) => n && n.id).filter((id) => typeof id === 'string');
    } catch (error) {
      return [];
    }
  }

  function closeAll() {
    for (const key of [...live.keys()]) close(key);
  }

  function notice(plan, onClick) {
    const notification = new Notification({ title: plan.title, body: plan.body });
    notification.on('click', () => onClick());
    notification.on('close', () => notices.delete(notification));
    notices.add(notification);
    if (notices.size > MAX_NOTICES) notices.delete(notices.values().next().value);
    notification.show();
  }

  return { show, close, closeAll, notice, removeDelivered, deliveredIds };
}

module.exports = { MAX_NOTICES, actionIndexOf, replyTextOf, createPresenter };
