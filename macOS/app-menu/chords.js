
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
  { chord: 'Cmd+Enter', owner: 'web/src/plugins/huddle/HuddleBody.svelte:416, TaskManagerAskForm.svelte:85, DrawerSearch.svelte:242' },
  { chord: 'Cmd+,', owner: 'web/src/lib/settings-page/settings-shortcut.ts:27 (same destination: Settings)', shared: { id: 'carnivore.settings' } },
  { chord: 'Cmd+[', owner: 'web/src/lib/app-keys/chords.ts (history back)', shared: { id: 'go.back' } },
  { chord: 'Cmd+]', owner: 'web/src/lib/app-keys/chords.ts (history forward)', shared: { id: 'go.forward' } },
  { chord: 'Cmd+<', owner: 'web/src/lib/app-keys/chords.ts (previous tab)' },
  { chord: 'Cmd+>', owner: 'web/src/lib/app-keys/chords.ts (next tab)' },
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => ({ chord: `Cmd+${n}`, owner: 'web/src/lib/app-keys/chords.ts (layout tab)' })),
  { chord: 'Cmd+K', owner: 'web/src/lib/app-keys/chords.ts (command palette)' },
  { chord: 'Ctrl+Shift+K', owner: 'web/src/lib/app-keys/chords.ts (command palette, off a mac)' },
  { chord: 'Shift+Cmd+P', owner: 'web/src/lib/app-keys/chords.ts (command palette, actions)' },
  { chord: 'Ctrl+Cmd+=', owner: 'web/src/lib/app-keys/chords.ts (terminal text bigger)' },
  { chord: 'Ctrl+Cmd+-', owner: 'web/src/lib/app-keys/chords.ts (terminal text smaller)' },
  { chord: 'Ctrl+Cmd+0', owner: 'web/src/lib/app-keys/chords.ts (terminal text reset)' },
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

const CARET_KEYS = new Set(['arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown']);
const DELETE_KEYS = new Set(['backspace', 'delete']);

function isTextEditing(mods, key) {
  const edits = mods.includes('cmd') || mods.includes('alt');
  return edits && (CARET_KEYS.has(key) || DELETE_KEYS.has(key));
}

function refusalFor(item, accelerator, taken) {
  const { canon, mods, key } = normalize(accelerator);
  if (!mods.includes('cmd') && !isFunctionKey(key)) {
    return mods.includes('ctrl') ? 'Ctrl without Cmd is a terminal control code'
      : mods.includes('alt') ? 'Option without Cmd is the terminal Meta key' : 'a key without Cmd belongs to the terminal';
  }
  if (isTextEditing(mods, key)) return 'text editing: the caret and delete keys belong to the focused field';
  const reserved = RESERVED_BY_CHORD.get(canon);
  if (reserved) {
    const shared = reserved.shared;
    if (!(shared && ((shared.role && shared.role === item.role) || (shared.id && shared.id === item.id)))) return `read by ${reserved.owner}`;
  }
  const holder = taken && taken.get(canon);
  if (holder && holder !== item.id) return `already the shortcut of the menu item ${holder}`;
  const builtIn = Object.entries(ROLE_ACCELERATORS).find(([role, acc]) => role !== item.role && normalize(acc).canon === canon);
  return builtIn ? `the built-in accelerator of the ${builtIn[0]} role` : null;
}

function explicitAccelerators(template) {
  const taken = new Map();
  const walk = (items) => {
    for (const item of items || []) {
      if (item.accelerator && item.id) taken.set(normalize(item.accelerator).canon, item.id);
      walk(item.submenu);
    }
  };
  walk(template);
  return taken;
}

function auditAccelerators(template) {
  const found = [];
  const walk = (items) => {
    for (const item of items || []) {
      const accelerator = item.accelerator || (item.role ? ROLE_ACCELERATORS[item.role] : undefined);
      const reason = accelerator ? refusalFor(item, accelerator) : null;
      if (reason) found.push({ id: item.id || item.role || String(accelerator), chord: accelerator, reason });
      walk(item.submenu);
    }
  };
  walk(template);
  return found;
}

module.exports = { explicitAccelerators, refusalFor, RESERVED_CHORDS, ROLE_ACCELERATORS, normalize, auditAccelerators };
