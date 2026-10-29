
'use strict';

const MODIFIERS = { cmd: 'cmd', command: 'cmd', cmdorctrl: 'cmd', commandorcontrol: 'cmd', super: 'cmd', meta: 'cmd',
  ctrl: 'ctrl', control: 'ctrl', alt: 'alt', option: 'alt', altgr: 'alt', shift: 'shift' };
const ORDER = ['ctrl', 'alt', 'shift', 'cmd'];
const KEYS = { return: 'enter', esc: 'escape', plus: '+', space: ' ' };

function normalize(accelerator) {
  const parts = String(accelerator).split('+');
  const key = (parts[parts.length - 1] === '' ? '+' : parts[parts.length - 1]).toLowerCase();
  const mods = new Set();
  for (const part of parts.slice(0, parts[parts.length - 1] === '' ? -2 : -1)) {
    const mod = MODIFIERS[part.toLowerCase()];
    if (mod) mods.add(mod);
  }
  const ordered = ORDER.filter((m) => mods.has(m));
  const folded = KEYS[key] || key;
  return { canon: [...ordered, folded].join('+'), mods: ordered, key: folded };
}

const RESERVED_CHORDS = Object.freeze([
  { chord: 'Cmd+C', owner: 'client/js/clipboard.js:94 (xterm copy)', shared: { role: 'copy' } },
  { chord: 'Cmd+V', owner: 'client/js/clipboard.js:94 (xterm paste)', shared: { role: 'paste' } },
  { chord: 'Cmd+F', owner: 'web/src/lib/terminal-search/search-keys.ts:172' },
  { chord: 'Cmd+G', owner: 'web/src/lib/terminal-search/search-keys.ts:173' },
  { chord: 'Shift+Cmd+G', owner: 'web/src/lib/terminal-search/search-keys.ts:174' },
  { chord: 'Cmd+S', owner: 'web/src/lib/open-files/FileScreen.svelte:205' },
  { chord: 'Shift+Cmd+Enter', owner: 'web/src/opscenter/engine/layout-zoom.svelte.ts:146' },
  { chord: 'Cmd+Enter', owner: 'web/src/cplugs/huddle/HuddleBody.svelte:416, TaskManagerAskForm.svelte:85, DrawerSearch.svelte:242' },
  { chord: 'Cmd+,', owner: 'web/src/lib/settings-page/settings-shortcut.ts:27 (same destination: Settings)', shared: { id: 'carnivore.settings' } },
  { chord: 'Ctrl+<any>', owner: 'xterm: control codes (rule 1)' },
  { chord: 'Alt+<any>', owner: 'xterm: Meta-b/f/d and word movement when macOptionIsMeta is on (rule 1)' },
  { chord: 'Shift+Enter', owner: 'client/js/terminal.js:582 (sends ESC+CR) (rule 1)' },
  { chord: 'Escape', owner: 'xterm / Claude Code (rule 1)' },
  { chord: 'Tab', owner: 'xterm / Claude Code (rule 1)' },
]);

const ROLE_ACCELERATORS = Object.freeze({
  undo: 'Cmd+Z', redo: 'Shift+Cmd+Z', cut: 'Cmd+X', copy: 'Cmd+C', paste: 'Cmd+V', selectAll: 'Cmd+A',
  reload: 'Cmd+R', forceReload: 'Shift+Cmd+R', toggleDevTools: 'Alt+Cmd+I',
  resetZoom: 'Cmd+0', zoomIn: 'Cmd+Plus', zoomOut: 'Cmd+-', togglefullscreen: 'Ctrl+Cmd+F',
  minimize: 'Cmd+M', close: 'Cmd+W', hide: 'Cmd+H', hideOthers: 'Alt+Cmd+H', quit: 'Cmd+Q',
});

const RESERVED_BY_CHORD = new Map(RESERVED_CHORDS.filter((r) => !r.chord.includes('<')).map((r) => [normalize(r.chord).canon, r]));

function isFunctionKey(key) {
  return /^f([1-9]|1[0-9]|20)$/.test(key);
}

function auditAccelerators(template) {
  const found = [];
  const walk = (items) => {
    for (const item of items || []) {
      const explicit = item.accelerator;
      const inherited = !explicit && item.role && item.registerAccelerator !== false ? ROLE_ACCELERATORS[item.role] : undefined;
      const accelerator = explicit || inherited;
      if (accelerator && item.registerAccelerator !== false) check(item, accelerator);
      walk(item.submenu);
    }
  };
  const check = (item, accelerator) => {
    const id = item.id || item.role || String(accelerator);
    const { canon, mods, key } = normalize(accelerator);
    if (!mods.includes('cmd') && !isFunctionKey(key)) {
      const reason = mods.includes('ctrl') ? 'Ctrl without Cmd is a terminal control code'
        : mods.includes('alt') ? 'Option without Cmd is the terminal Meta key' : 'a key without Cmd belongs to the terminal';
      found.push({ id, chord: accelerator, reason });
      return;
    }
    const reserved = RESERVED_BY_CHORD.get(canon);
    if (!reserved) return;
    const shared = reserved.shared;
    if (shared && ((shared.role && shared.role === item.role) || (shared.id && shared.id === item.id))) return;
    found.push({ id, chord: accelerator, reason: `read by ${reserved.owner}` });
  };
  walk(template);
  return found;
}

module.exports = { RESERVED_CHORDS, ROLE_ACCELERATORS, normalize, auditAccelerators };
