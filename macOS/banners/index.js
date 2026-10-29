
'use strict';

const model = require('./model');
const { createPresenter } = require('./presenter-electron');
const { createAnswerer } = require('./answer');
const { shouldMirror } = require('./mirror');
const { createColdLaunch } = require('./launch');

const APPROVALS_ROUTE = '/api/v1/approvals';
const PREFERENCES_ROUTE = '/api/v1/preferences';

const NOOP = Object.freeze({
  onApprovals: async () => {},
  press: async () => ({ outcome: 'ignored' }),
  reply: async () => ({ outcome: 'ignored' }),
  coldLaunch: async () => ({ outcome: 'ignored' }),
  posting: async () => false,
  mirrorAllowed: async () => true,
  closeAll: () => {},
});

function createBanners(deps) {
  if (deps.platform !== 'darwin' || !deps.Notification) return NOOP;
  let supportedMemo = null;
  const supported = () => (supportedMemo === null ? (supportedMemo = !!deps.Notification.isSupported()) : supportedMemo);
  const entries = new Map();
  const cap = deps.cap === undefined ? model.VISIBLE_ACTION_CAP : deps.cap;
  let chain = null;
  let again = false;

  const ids = (entry) => entry.plan.buttons.map((_b, i) => model.encodeActionId(entry.item.session_id, model.keyFingerprint(entry.item), entry.step, i));
  const answerer = createAnswerer({
    entries, getApi: deps.getApi, openApproval: deps.openApproval, isLocked: deps.isLocked,
    closeBanner: (entry) => presenter.close(entry.key),
    showStep: (entry) => showStep(entry),
    notice: (kind, entry) => notice(kind, entry),
  });
  const presenter = createPresenter({
    Notification: deps.Notification,
    onAction: (id) => { answerer.press(id).catch((error) => console.warn('[banners] press failed:', error && error.message)); },
    onReply: (key, text) => { answerer.reply(key, text).catch((error) => console.warn('[banners] reply failed:', error && error.message)); },
    onClick: (key) => {
      const entry = entries.get(key);
      if (entry) { entry.done = true; presenter.close(key); deps.openApproval(entry.item.session_id); }
    },
    onFailed: (key, error) => console.warn('[banners] macOS refused a banner:', key.slice(0, 24), String((error && error.message) || error)),
  });

  function showStep(entry) {
    entry.plan = model.planFor(entry.item, { t: deps.t, hideCommand: entry.hideCommand, step: entry.step, cap });
    presenter.show(entry.key, entry.plan, ids(entry));
  }

  const NOTICE_KEYS = {
    changed: ['desktop.banner.title_changed', 'desktop.banner.body_changed'],
    failed: ['desktop.banner.title_failed', 'desktop.banner.answer_failed'],
    too_long: ['desktop.banner.title_too_long', 'desktop.banner.body_too_long'],
    bad_chars: ['desktop.banner.title_bad_chars', 'desktop.banner.body_bad_chars'],
  };

  function notice(kind, entry) {
    const [title, body] = NOTICE_KEYS[kind] || NOTICE_KEYS.failed;
    presenter.notice({
      title: deps.t(title),
      body: deps.t(body, { max: String(model.MAX_REPLY) }),
    }, () => deps.openApproval(entry.item.session_id));
  }

  async function readPrefs(api) {
    const result = await api.getAuthed(PREFERENCES_ROUTE);
    if (!result.reachable || !result.data || typeof result.data.values !== 'object' || result.data.values === null) return null;
    const values = result.data.values;
    return { banners: values.desktop_banners === true, hideCommand: values.desktop_banner_hide_command === true,
      asksOnly: values.desktop_notify_asks_only === true };
  }

  function closeAll() {
    presenter.closeAll();
    entries.clear();
  }

  async function readItems() {
    const api = deps.getApi();
    if (!api) return null;
    const result = await api.getAuthed(APPROVALS_ROUTE);
    return result.reachable && result.data && Array.isArray(result.data.items) ? result.data.items : null;
  }

  function makeEntry(key, item) {
    const entry = { key, item, step: 0, held: [], busy: false, done: false, hideCommand: true, plan: null };
    entry.plan = model.planFor(item, { t: deps.t, hideCommand: true, cap });
    entries.set(key, entry);
    return entry;
  }

  const coldLaunch = createColdLaunch({
    readItems, entries, makeEntry, answerer, notice, openApproval: deps.openApproval, removeDelivered: presenter.removeDelivered,
    sleep: deps.sleep, waitMs: deps.coldWaitMs, stepMs: deps.coldStepMs, now: deps.now, coldLockKnown: deps.coldLockKnown,
  });
  let pruned = false;

  async function pruneDelivered(wanted) {
    pruned = true;
    for (const id of await presenter.deliveredIds()) {
      const parts = model.decodeNotificationId(id);
      if (parts && !wanted.has(`${parts.sessionId}|${parts.fingerprint}`)) presenter.removeDelivered(id);
    }
  }

  async function reconcile() {
    const api = deps.getApi();
    if (!api) { closeAll(); return; }
    const result = await api.getAuthed(APPROVALS_ROUTE);
    if (!result.reachable || !result.data || !Array.isArray(result.data.items)) return;
    const wanted = new Map();
    for (const item of result.data.items) {
      if (item && item.host !== undefined && item.host !== 'local') continue;
      if (item && typeof item.session_id === 'string') wanted.set(model.itemKey(item), item);
    }
    for (const [key, entry] of [...entries]) {
      if (wanted.has(key)) continue;
      presenter.close(key);
      entries.delete(key);
      entry.held = [];
    }
    let prefs = null;
    if (!pruned) {
      prefs = await readPrefs(api);
      if (prefs && prefs.banners) await pruneDelivered(wanted);
    }
    for (const [key, item] of wanted) {
      if (entries.has(key) || deps.isWindowFocused()) continue;
      prefs = prefs || await readPrefs(api);
      const verdict = model.bannersDeliverable({ prefOn: !!(prefs && prefs.banners), permission: deps.readPermission(), apiPresent: true });
      if (!verdict.ok || !supported()) return;
      const entry = { key, item, step: 0, held: [], busy: false, done: false, hideCommand: prefs.hideCommand, plan: null };
      const plan = model.planFor(item, { t: deps.t, hideCommand: entry.hideCommand, cap });
      if (!plan.post) continue;
      entries.set(key, entry);
      showStep(entry);
    }
  }

  function onApprovals() {
    if (chain) { again = true; return chain; }
    chain = (async () => {
      do {
        again = false;
        try {
          await reconcile();
        } catch (error) {
          console.warn('[banners] sync failed:', error && error.message);
        }
      } while (again);
    })().finally(() => { chain = null; });
    return chain;
  }

  async function posting() {
    const api = deps.getApi();
    let prefs = null;
    try {
      prefs = api ? await readPrefs(api) : null;
    } catch (error) {
      prefs = null;
    }
    return model.bannersDeliverable({ prefOn: !!(prefs && prefs.banners), permission: deps.readPermission(), apiPresent: !!api }).ok && supported();
  }

  async function mirrorAllowed(askSessionId) {
    const api = deps.getApi();
    let prefs = null;
    try {
      prefs = api ? await readPrefs(api) : null;
    } catch (error) {
      prefs = null;
    }
    if (!prefs || !prefs.banners || !supported()) return false;
    return shouldMirror({ asksOnly: prefs.asksOnly, askSessionId });
  }

  return { onApprovals, press: answerer.press, reply: answerer.reply, coldLaunch: coldLaunch.handle, posting, mirrorAllowed, closeAll };
}

module.exports = { APPROVALS_ROUTE, PREFERENCES_ROUTE, NOOP, createBanners };
