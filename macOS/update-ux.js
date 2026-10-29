'use strict';

const fs = require('node:fs');
const path = require('node:path');

const PENDING_STATES = Object.freeze(['available', 'downloading', 'ready']);
const NO_UX = Object.freeze({ trayIcon: 'normal', menuRow: null, notify: false });

function updateUxFor(update, autoOn) {
  const state = update && update.state;
  if (autoOn === true || !PENDING_STATES.includes(state)) return NO_UX;
  const version = (update.version && String(update.version)) || '';
  return {
    trayIcon: 'update',
    menuRow: { version, label: `update to ${version}: download, install and restart` },
    notify: state === 'available',
  };
}

function createNoticeMemo({ dir, fsImpl = fs }) {
  const file = () => path.join(dir(), 'update-notice.json');
  return {
    shouldAnnounce(version) {
      if (!version) return false;
      let last = null;
      try {
        last = JSON.parse(fsImpl.readFileSync(file(), 'utf8')).version;
      } catch (err) {
        if (err.code !== 'ENOENT') console.warn('[update-ux] notice memo not read:', err.message);
      }
      if (last === version) return false;
      try {
        fsImpl.writeFileSync(file(), JSON.stringify({ version }));
      } catch (err) {
        console.warn('[update-ux] notice memo not written:', err.message);
      }
      return true;
    },
  };
}

module.exports = { PENDING_STATES, updateUxFor, createNoticeMemo };
