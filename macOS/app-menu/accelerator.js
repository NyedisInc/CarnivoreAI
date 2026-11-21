
'use strict';

const MODIFIERS = Object.freeze({
  cmd: 'Cmd', command: 'Cmd', meta: 'Cmd', super: 'Cmd', commandorcontrol: 'Cmd', cmdorctrl: 'Cmd',
  ctrl: 'Ctrl', control: 'Ctrl', alt: 'Alt', option: 'Alt', opt: 'Alt', shift: 'Shift',
});

const NAMED_KEYS = Object.freeze({
  arrowup: 'Up', arrowdown: 'Down', arrowleft: 'Left', arrowright: 'Right', up: 'Up', down: 'Down', left: 'Left', right: 'Right',
  enter: 'Return', return: 'Return', escape: 'Escape', esc: 'Escape', space: 'Space', tab: 'Tab', backspace: 'Backspace',
  delete: 'Delete', home: 'Home', end: 'End', pageup: 'PageUp', pagedown: 'PageDown', plus: 'Plus', '+': 'Plus',
});

const PUNCTUATION = new Set('[]{}()<>,.;:\'"/\\|?!@#$%^&*-_=~`'.split(''));

function mapKey(key) {
  const lower = key.toLowerCase();
  if (NAMED_KEYS[lower]) return NAMED_KEYS[lower];
  if (/^[a-z0-9]$/.test(lower)) return lower.toUpperCase();
  if (/^f([1-9]|1[0-9]|2[0-4])$/.test(lower)) return lower.toUpperCase();
  return PUNCTUATION.has(key) ? key : null;
}

function toAccelerator(chord) {
  if (typeof chord !== 'string' || !chord.trim() || chord.length > 40) return null;
  const raw = chord.trim();
  const plusKey = raw.endsWith('++');
  const parts = (plusKey ? raw.slice(0, -2) : raw).split('+');
  const keyText = plusKey ? '+' : parts.pop();
  const mods = [];
  for (const word of parts) {
    const mod = MODIFIERS[word.toLowerCase()];
    if (!mod) return null;
    if (!mods.includes(mod)) mods.push(mod);
  }
  const key = mapKey(keyText || '');
  if (!key) return null;
  const order = ['Ctrl', 'Alt', 'Shift', 'Cmd'];
  return [...order.filter((m) => mods.includes(m)), key].join('+');
}

module.exports = { toAccelerator };
