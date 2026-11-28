
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

function analyzeListingRows(list, led) {
  const newest = new Map();
  const waiting = [];
  const questions = new Set();
  let count = 0;
  if (Array.isArray(list)) {
    for (const info of list) {
      if (!info || typeof info !== 'object') continue;
      const validRow = rows.isRow(info);
      if (validRow && rows.isLocal(info) && typeof info.project_name === 'string' && info.project_name) {
        newest.set(info.project_name, Math.max(newest.get(info.project_name) || 0, rows.recency(info)));
      }
      const kind = needYou.needYouKind(info, led);
      if (kind) {
        count += 1;
        if (validRow) {
          waiting.push({ info, kind });
          if (kind === 'question') questions.add(rows.rowKey(info));
        }
      }
    }
  }
  const projects = [...newest.entries()].sort((a, b) => b[1] - a[1]).slice(0, MAX_RECENT).map(([name]) => name);
  return { count, projects, waiting, questions };
}

function buildDockMenuTemplate({ rows: list, led, t, openApp, openApproval, sessionLink, projects: preProjects, waiting: preWaiting }) {
  const items = [{ id: 'new', label: t('menubar.new_session'), click: () => openApp('') }];
  const projects = preProjects || recentProjects(list);
  if (projects.length) {
    items.push({ id: 'recent', label: t('menubar.dock.recent_projects'), submenu: projects.map((name) => ({
      id: `project:${name}`, label: clip(name), click: () => openApp(`session/${encodeURIComponent(name)}`) })) });
  }
  const waiting = preWaiting || needYou.waitingRows(list.filter(rows.isRow), led);
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
  if (!dock) return { update() {}, clear() {}, bounce() {} };
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
      const { count, projects, waiting, questions: now } = analyzeListingRows(listing.rows, env.led);
      const text = count > 0 ? String(count) : '';
      if (text !== badge) { dock.setBadge(text); badge = text; }
      const template = buildDockMenuTemplate({ rows: listing.rows, led: env.led, t: env.t, openApp: deps.openApp,
        openApproval: deps.openApproval, sessionLink: deps.sessionLink, projects, waiting });
      const signature = JSON.stringify(template);
      if (signature !== menuSignature) { dock.setMenu(deps.Menu.buildFromTemplate(template)); menuSignature = signature; }
      let arrived = false;
      for (const key of now) { if (!questions.has(key)) { arrived = true; break; } }
      questions = now;
      const focused = !!(deps.isWindowFocused && deps.isWindowFocused());
      if (seeded && arrived && !focused) dock.bounce('informational');
      seeded = true;
    },
    bounce() { dock.bounce('informational'); },
    clear() {
      dock.setBadge('');
      dock.setMenu(deps.Menu.buildFromTemplate([]));
      badge = ''; menuSignature = null; questions = new Set(); seeded = false;
    },
  };
}

module.exports = { createDockPresence, buildDockMenuTemplate, recentProjects, questionKeys };
