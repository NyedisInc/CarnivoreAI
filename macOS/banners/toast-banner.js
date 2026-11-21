
'use strict';

const kind = require('./kind');
const { createThumbnails } = require('./thumbnail');

const CARD_ROUTE = '/api/v1/notifications/cards/';
const SETTINGS_ROUTE = '/api/v1/notifications/settings';
const STYLES_ROUTE = '/api/v1/notifications/styles';
const TOASTS_ROUTE = '/api/v1/toasts?unacked=true&limit=50';
const MESSAGES_ROUTE = '/api/v1/crosstalk/messages';
const RESPAWN_ROUTE = '/api/v1/sessions/respawn';
const INSTALL_ROUTE = '/api/v1/app-update/install';
const RESTART_AGENTS_ROUTE = '/api/v1/notifications/agent-update/restart';
const HUDDLE_ITEMS = '/api/v1/cplugs/huddle/items/';
const MAX_HELD = 100;
const ASK_LOOKUPS = 3;

function createToastBanner(deps) {
  const held = new Map();
  const asks = new Map();
  const images = new Map();
  const thumbs = deps.thumbs || createThumbnails({ nativeImage: deps.nativeImage });
  const busy = new Set();

  const image = (file) => {
    if (!images.has(file)) images.set(file, deps.nativeImage.createFromPath(file));
    return images.get(file);
  };

  async function read(api, route) {
    try {
      const result = await api.getAuthed(route);
      return result.reachable ? result.data : null;
    } catch (error) {
      return null;
    }
  }

  async function fetchPlan(api, toastId) {
    let card;
    try {
      card = await api.getAuthed(CARD_ROUTE + encodeURIComponent(toastId));
    } catch (error) {
      return null;
    }
    if (!card.reachable) return card.status === 404 ? { missing: true } : null;
    const type = String(card.data.type || '');
    if (card.data.test_target === 'app') return { missing: true };
    const [settings, styles] = await Promise.all([read(api, SETTINGS_ROUTE), read(api, STYLES_ROUTE)]);
    const cell = settings && settings.desktop ? settings.desktop[type] : undefined;
    const style = styles && styles.styles ? styles.styles[type] : undefined;
    const desktopOn = card.data.test_target === 'desktop' ? true : (cell ? cell.value : undefined);
    return { response: card.data, desktopOn, corner: style ? style.corner : undefined };
  }

  function trim() {
    if (held.size > MAX_HELD) held.delete(held.keys().next().value);
  }

  function close(id) {
    const entry = held.get(id);
    held.delete(id);
    asks.delete(id);
    if (entry && entry.notification) entry.notification.close();
    deps.corner.hideKey(id);
    thumbs.release(id);
  }

  /* could not be reached */
  async function write(api, route, body) {
    try {
      const result = await api.sendAuthed(route, body, 'POST');
      return !!(result && result.reachable && !(result.data && result.data.ok === false));
    } catch (error) {
      console.warn('[toast-banner] write failed:', String((error && error.message) || error));
      return false;
    }
  }

  const sendable = (text) => typeof text === 'string' && text.trim() !== '' && [...text.trim()].length <= kind.MAX_REPLY && !/[\u0000-\u001f\u007f]/.test(text.trim());

  async function sendReply(entry, text) {
    const api = deps.getApi();
    if (!api || !sendable(text)) return false;
    const typed = text.trim();
    if (entry.plan.replyAction === 'answer') return answerSwarm(api, entry, typed);
    const to = entry.meta.session_id;
    return to ? write(api, MESSAGES_ROUTE, { to, text: typed }) : false;
  }

  async function answerSwarm(api, entry, text) {
    const item = entry.plan.item;
    return item ? write(api, `${HUDDLE_ITEMS}${item}/messages`, { text }) : false;
  }

  async function runRoute(entry, action) {
    const api = deps.getApi();
    if (!api) return false;
    if (action === 'install') return write(api, INSTALL_ROUTE, undefined);
    if (action === 'restart_agents') return write(api, RESTART_AGENTS_ROUTE, { toast_id: entry.meta.id });
    if (action === 'reopen') return entry.meta.tmux_name ? write(api, RESPAWN_ROUTE, { session_name: entry.meta.tmux_name }) : false;
    const positions = entry.plan.shown.card && Array.isArray(entry.plan.shown.card.positions) ? entry.plan.shown.card.positions : [];
    const says = positions[Number(action.slice(5)) - 1];
    return says && typeof says[1] === 'string' && sendable(says[1]) ? answerSwarm(api, entry, says[1].trim()) : false;
  }

  function press(id, action) {
    const entry = held.get(id);
    if (!entry) return;
    const url = entry.plan.shown.card && typeof entry.plan.shown.card.url === 'string' ? entry.plan.shown.card.url : '';
    if (action === 'later') { close(id); return; }
    if (action === 'copy_link') { if (/^https?:\/\//i.test(url)) deps.clipboard.writeText(url); return; }
    if (kind.ROUTE_ACTIONS.includes(action) || kind.PICK_ACTION.test(action)) {
      if (busy.has(id)) return;
      if (deps.isLocked && deps.isLocked()) { entry.open(); close(id); return; }
      busy.add(id);
      runRoute(entry, action).then((done) => { if (!done) entry.open(); }, () => entry.open()).finally(() => { busy.delete(id); close(id); });
      return;
    }
    if (action === 'open_link' && /^https?:\/\//i.test(url)) deps.shell.openExternal(url).catch(() => {});
    else entry.open();
    close(id);
  }

  async function present(input) {
    const api = deps.getApi();
    const id = input.meta && typeof input.meta.id === 'string' ? input.meta.id : '';
    if (!api || !id) return false;
    const fetched = await fetchPlan(api, id);
    if (fetched === null) return false;
    if (fetched.missing) return true;
    const plan = kind.planFromCard({ ...fetched, silent: input.silent });
    if (!plan.post) return true;
    const thumb = ['image', 'video', 'file'].includes(plan.kind) ? await thumbs.get(api, id, plan.kind, fetched.response) : null;
    if (thumb) plan.shown.mediaUrl = thumb.dataUrl;
    if (thumb) plan.icon = thumb.file;
    const options = kind.bannerOptions(plan, { id, groupId: input.meta.session_id || input.meta.tmux_name || undefined,
      image: (file) => (thumb && file === thumb.file ? deps.nativeImage.createFromPath(thumb.file) : image(file)) });
    const notification = new deps.Notification(options);
    const entry = { notification, plan, meta: input.meta, open: input.open };
    notification.on('action', (...args) => {
      const details = args[0];
      const index = details && Number.isInteger(details.actionIndex) ? details.actionIndex : args[1];
      const button = Number.isInteger(index) ? plan.buttons[index] : undefined;
      if (button) press(id, button.id);
    });
    notification.on('reply', (...args) => {
      const details = args[0];
      const typed = details && typeof details.reply === 'string' ? details.reply : args[1];
      sendReply(entry, typed).then((done) => { if (done) close(id); else if (sendable(typed)) entry.open(); }, () => {});
    });
    notification.on('click', () => { entry.open(); close(id); });
    held.set(id, entry);
    trim();
    notification.show();
    if (plan.corner) await deps.corner.show({ key: id, shown: plan.shown, autoHideMs: plan.autoHideMs });
    return true;
  }

  async function cornerForAsk(ask) {
    const api = deps.getApi();
    if (!api) return;
    const list = await read(api, TOASTS_ROUTE);
    const toasts = list && Array.isArray(list.toasts) ? list.toasts.filter((t) => t && t.session_id === ask.sessionId && typeof t.id === 'string') : [];
    for (const toast of toasts.slice(0, ASK_LOOKUPS)) {
      const fetched = await fetchPlan(api, toast.id);
      if (!fetched || fetched.missing) continue;
      const plan = kind.planFromCard(fetched);
      if (!kind.ASK_KINDS.includes(plan.kind)) continue;
      if (plan.post && plan.corner && (!ask.stillOpen || ask.stillOpen())) {
        asks.set(ask.key, ask.answer);
        await deps.corner.show({ key: ask.key, shown: plan.shown, autoHideMs: 0 });
      }
      return;
    }
  }

  function pressKey(key, action) {
    if (asks.has(key)) asks.get(key)(action);
    else press(key, action);
  }

  function cornerClosed(key) {
    asks.delete(key);
  }

  return { present, close, cornerForAsk, press: pressKey, cornerClosed };
}

module.exports = { CARD_ROUTE, createToastBanner };
