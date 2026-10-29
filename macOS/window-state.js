'use strict';

const nodeFs = require('fs');
const path = require('path');

const FILE = 'window-state.json';
const SAVE_DEBOUNCE_MS = 500;
const MIN_VISIBLE = 100;
const MIN_SIZE = 200;
const MAX_OPEN = 32;
const MAX_FIELD = 2200;

const finite = (n) => typeof n === 'number' && Number.isFinite(n);

function overlap(rect, area) {
  return {
    w: Math.max(0, Math.min(rect.x + rect.width, area.x + area.width) - Math.max(rect.x, area.x)),
    h: Math.max(0, Math.min(rect.y + rect.height, area.y + area.height) - Math.max(rect.y, area.y)),
  };
}

function fitToDisplays(saved, displays, fallback) {
  const base = { width: fallback.width, height: fallback.height };
  if (!saved || ![saved.x, saved.y, saved.width, saved.height].every(finite)) return base;
  if (saved.width < MIN_SIZE || saved.height < MIN_SIZE || !Array.isArray(displays)) return base;
  let best = null;
  for (const display of displays) {
    const area = display && display.workArea;
    if (!area) continue;
    const o = overlap(saved, area);
    if (o.w >= MIN_VISIBLE && o.h >= MIN_VISIBLE && (!best || o.w * o.h > best.score)) best = { area, score: o.w * o.h };
  }
  if (!best) return base;
  const { area } = best;
  const width = Math.min(saved.width, area.width);
  const height = Math.min(saved.height, area.height);
  const x = Math.max(area.x, Math.min(saved.x, area.x + area.width - width));
  const y = Math.max(area.y, Math.min(saved.y, area.y + area.height - height));
  return { x, y, width, height };
}

function createWindowState({ dir, key = 'main', getDisplays, fsImpl, timers }) {
  const fs = fsImpl || nodeFs;
  const clock = timers || { setTimeout, clearTimeout };
  const file = () => path.join(dir(), FILE);

  /* the whole file */
  function readAll() {
    let text;
    try {
      text = fs.readFileSync(file(), 'utf8');
    } catch (err) {
      if (err.code !== 'ENOENT') console.warn('[window-state] not readable, ignored:', err.message);
      return null;
    }
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === 'object' && parsed.windows && typeof parsed.windows === 'object' ? parsed : null;
    } catch (err) {
      console.warn('[window-state] corrupt, ignored:', err.message);
      return null;
    }
  }

  function commit(all) {
    fs.mkdirSync(dir(), { recursive: true });
    const tmp = `${file()}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(all), { mode: 0o600 });
    fs.renameSync(tmp, file());
  }

  function forKey(key) {
    function load() {
      const all = readAll();
      const rec = all && all.windows[key];
      if (!rec || ![rec.x, rec.y, rec.width, rec.height].every(finite)) return null;
      return { x: rec.x, y: rec.y, width: rec.width, height: rec.height, maximized: rec.maximized === true, fullScreen: rec.fullScreen === true };
    }

    function write(rec) {
      try {
        const all = readAll() || { version: 1, windows: {} };
        all.windows[key] = rec;
        commit(all);
      } catch (err) {
        console.warn('[window-state] not saved:', err.message);
      }
    }

    function track(win) {
      let timer = null;
      const save = () => {
        timer = null;
        if (win.isDestroyed()) return;
        const b = win.getNormalBounds();
        write({ x: b.x, y: b.y, width: b.width, height: b.height, maximized: win.isMaximized(), fullScreen: win.isFullScreen() });
      };
      const later = () => {
        if (timer) clock.clearTimeout(timer);
        timer = clock.setTimeout(save, SAVE_DEBOUNCE_MS);
      };
      win.on('resize', later);
      win.on('move', later);
      win.on('close', () => {
        if (timer) clock.clearTimeout(timer);
        save();
      });
    }

    return {
      load,
      bounds: (fallback, seed, preferSeed) => fitToDisplays((preferSeed === true && seed) || load() || seed || null, getDisplays(), fallback),
      track,
    };
  }

  function readOpen() {
    const all = readAll();
    const list = all && Array.isArray(all.open) ? all.open : [];
    const ok = (v) => typeof v === 'string' && v.length > 0 && v.length <= MAX_FIELD;
    return list.filter((e) => e && ok(e.key) && ok(e.kind) && ok(e.path)).slice(0, MAX_OPEN).map((e) => ({ key: e.key, kind: e.kind, path: e.path }));
  }

  function writeOpen(list) {
    try {
      const all = readAll() || { version: 1, windows: {} };
      all.open = list.slice(0, MAX_OPEN);
      const keep = new Set(['main', ...all.open.map((e) => e.key)]);
      for (const k of Object.keys(all.windows)) if (!keep.has(k)) delete all.windows[k];
      commit(all);
    } catch (err) {
      console.warn('[window-state] open list not saved:', err.message);
    }
  }

  return { ...forKey(key), forKey, readOpen, writeOpen };
}

module.exports = { FILE, SAVE_DEBOUNCE_MS, MIN_VISIBLE, MIN_SIZE, fitToDisplays, createWindowState };
