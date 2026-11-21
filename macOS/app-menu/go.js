
'use strict';

const { sendVerb } = require('./commands');
const { toAccelerator } = require('./accelerator');
const { refusalFor } = require('./chords');

const RECENT_CHANNEL = 'carnivore:go-recent';
const KEYS_CHANNEL = 'carnivore:go-keys';
const KEY_ACTIONS = Object.freeze({ 'history.back': ['go.back', 'Cmd+['], 'history.forward': ['go.forward', 'Cmd+]'] });
const RECENT_MAX = 10;
const LABEL_MAX = 80;

function cleanRecent(labels) {
  if (!Array.isArray(labels) || labels.length > RECENT_MAX) return null;
  const out = [];
  for (const label of labels) {
    if (typeof label !== 'string') return null;
    // eslint-disable-next-line no-control-regex
    const clean = label.replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, LABEL_MAX);
    if (!clean) return null;
    out.push(clean);
  }
  return out;
}

function cleanKeys(keys) {
  if (!keys || typeof keys !== 'object' || Array.isArray(keys)) return null;
  const out = {};
  for (const id of Object.keys(KEY_ACTIONS)) {
    if (!Array.isArray(keys[id])) continue;
    out[id] = keys[id].filter((c) => typeof c === 'string' && c.length <= 40).slice(0, 4);
  }
  return out;
}

function acceleratorFor(actionId, keys, taken) {
  const [verbId, builtIn] = KEY_ACTIONS[actionId];
  if (!keys || !(actionId in keys)) return builtIn;
  for (const chord of keys[actionId]) {
    const accelerator = toAccelerator(chord);
    if (accelerator && !refusalFor({ id: verbId }, accelerator, taken)) return accelerator;
  }
  return undefined;
}

function build({ t, appWindow, recent, keys, taken }) {
  const chords = keys ? keys() : undefined;
  const verb = (id, label, extra) => ({ id, label, click: () => sendVerb(appWindow, id), ...extra });
  const labels = (recent ? recent() : []).slice(0, RECENT_MAX);
  const places = labels.length
    ? labels.map((label, i) => verb(`go.recent.${i}`, label))
    : [{ id: 'go.recent.none', label: t('menubar.menu.no_recent'), enabled: false }];
  return {
    id: 'go',
    label: t('menubar.menu.go'),
    submenu: [
      verb('go.back', t('menubar.menu.back'), { accelerator: acceleratorFor('history.back', chords, taken) }),
      verb('go.forward', t('menubar.menu.forward'), { accelerator: acceleratorFor('history.forward', chords, taken) }),
      { type: 'separator' },
      ...places,
    ],
  };
}

module.exports = { KEYS_CHANNEL, cleanKeys, RECENT_CHANNEL, RECENT_MAX, cleanRecent, build };
