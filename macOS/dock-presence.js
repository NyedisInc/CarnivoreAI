
'use strict';

const needYou = require('./tray-menu/need-you');
const rows = require('./tray-menu/session-rows');
const { clip } = require('./tray-menu/strings');

const MAX_RECENT = 5;
const MAX_WAITING = 8;

function recentProjects(list) {
  const newest = new Map();
  for (const info of list) {
    if (!rows.isRow(info) || !rows.isLocal(info) || typeof info.project_name !== 'string' || !info.project_name) continue;
    newest.set(info.project_name, Math.max(newest.get(info.project_name) || 0, rows.recency(info)));
  }
  return [...newest.entries()].sort((a, b) => b[1] - a[1]).slice(0, MAX_RECENT).map(([name]) => name);
}

function buildDockMenuTemplate({ rows: list, led, t, openApp, openApproval, sessionLink }) {
  const items = [{ id: 'new', label: t('menubar.new_session'), click: () => openApp('') }];
  const projects = recentProjects(list);
  if (projects.length) {
    items.push({ id: 'recent', label: t('menubar.dock.recent_projects'), submenu: projects.map((name) => ({
      id: `project:${name}`, label: clip(name), click: () => openApp(`session/${encodeURIComponent(name)}`) })) });
  }
  const waiting = needYou.waitingRows(list.filter(rows.isRow), led);
  if (waiting.length) {
    items.push({ type: 'separator' }, { id: 'needyou', label: t('menubar.need_you', { count: waiting.length }), enabled: false });
    for (const { info, kind } of waiting.slice(0, MAX_WAITING)) {
      const a = { tmuxName: info.tmux_session || null, sessionId: info.session.id };
      items.push({ id: `wait:${rows.rowKey(info)}:${kind}`, label: clip(rows.rowLabel(info)),
        sublabel: t(kind === 'question' ? 'menubar.need_you.question' : 'menubar.need_you.gate'),
        click: () => { if (kind !== 'question' || !openApproval(a.sessionId)) openApp(sessionLink(a)); } });
    }
  }
  return items;
}

function questionKeys(list, led) {
  return new Set(needYou.waitingRows(list.filter(rows.isRow), led).filter((w) => w.kind === 'question').map((w) => rows.rowKey(w.info)));
}

function createDockPresence(deps) {
  const dock = deps.platform === 'darwin' && deps.app && deps.app.dock ? deps.app.dock : null;
  if (!dock) return { update() {}, clear() {} };
  let badge = null;
  let menuSignature = null;
  let questions = new Set();
  let seeded = false;
  return {
    update(listing, env) {
      if (!listing || !Array.isArray(listing.rows) || !listing.reachable || !env || !env.led) {
        seeded = false;
        return;
      }
      const count = needYou.needYouCount(listing.rows, env.led);
      const text = count > 0 ? String(count) : '';
      if (text !== badge) { dock.setBadge(text); badge = text; }
      const template = buildDockMenuTemplate({ rows: listing.rows, led: env.led, t: env.t, openApp: deps.openApp,
        openApproval: deps.openApproval, sessionLink: deps.sessionLink });
      const signature = JSON.stringify(template);
      if (signature !== menuSignature) { dock.setMenu(deps.Menu.buildFromTemplate(template)); menuSignature = signature; }
      const now = questionKeys(listing.rows, env.led);
      const arrived = [...now].some((key) => !questions.has(key));
      questions = now;
      const focused = !!(deps.isWindowFocused && deps.isWindowFocused());
      if (seeded && arrived && !focused) dock.bounce('informational');
      seeded = true;
    },
    clear() {
      dock.setBadge('');
      dock.setMenu(deps.Menu.buildFromTemplate([]));
      badge = ''; menuSignature = null; questions = new Set(); seeded = false;
    },
  };
}

module.exports = { createDockPresence, buildDockMenuTemplate, recentProjects, questionKeys };
