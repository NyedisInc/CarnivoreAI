
'use strict';

const { sendVerb } = require('./commands');

const RECENT_CHANNEL = 'carnivore:go-recent';
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

function build({ t, appWindow, recent }) {
  const verb = (id, label, extra) => ({ id, label, click: () => sendVerb(appWindow, id), ...extra });
  const labels = (recent ? recent() : []).slice(0, RECENT_MAX);
  const places = labels.length
    ? labels.map((label, i) => verb(`go.recent.${i}`, label))
    : [{ id: 'go.recent.none', label: t('menubar.menu.no_recent'), enabled: false }];
  return {
    id: 'go',
    label: t('menubar.menu.go'),
    submenu: [
      verb('go.back', t('menubar.menu.back'), { accelerator: 'Cmd+[', registerAccelerator: false }),
      verb('go.forward', t('menubar.menu.forward'), { accelerator: 'Cmd+]', registerAccelerator: false }),
      { type: 'separator' },
      ...places,
    ],
  };
}

module.exports = { RECENT_CHANNEL, RECENT_MAX, cleanRecent, build };
