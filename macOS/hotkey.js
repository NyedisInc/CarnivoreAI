
'use strict';

const DEFAULT_ACCELERATOR = 'Ctrl+Option+Cmd+C';
const REASON_TAKEN = 'another app already uses it';
const REASON_INVALID = 'not a valid combination';

const REASON_UNSAFE = 'it would take a shortcut every app uses';
const MODIFIER_CANON = { control: 'ctrl', option: 'alt', command: 'cmd', super: 'cmd', meta: 'cmd', cmdorctrl: 'cmd', commandorcontrol: 'cmd' };
const SYSTEM_CHORDS = new Set(['cmd+q+shift', 'cmd+ctrl+q', 'alt+cmd+escape', 'alt+cmd+esc', '3+cmd+shift', '4+cmd+shift', '5+cmd+shift', 'alt+cmd+d']);

function isSafeAccelerator(accelerator) {
  const parts = String(accelerator).split('+');
  const key = String(parts.pop()).toLowerCase();
  const mods = new Set(parts.map((m) => MODIFIER_CANON[m.toLowerCase()] || m.toLowerCase()));
  if (mods.size < 2 && !/^f(?:[1-9]|1[0-9]|2[0-4])$/.test(key)) return false;
  return !SYSTEM_CHORDS.has([...mods, key].sort().join('+'));
}

const PREFERENCES_ROUTE = '/api/v1/preferences';

/* an absent field is the default */
function acceleratorOf(values) {
  if (typeof values !== 'object' || values === null) return null;
  return typeof values.desktop_hotkey === 'string' ? values.desktop_hotkey : DEFAULT_ACCELERATOR;
}

async function readPreference(api) {
  if (!api) return null;
  const result = await api.getAuthed(PREFERENCES_ROUTE);
  return acceleratorOf(result && result.reachable && result.data ? result.data.values : null);
}

function createHotkey({ globalShortcut, readAccelerator, onFire, report, store = null }) {
  let current = null;
  let held = false;
  let stopped = false;

  function apply(next) {
    if (current && held) {
      try {
        globalShortcut.unregister(current);
      } catch (error) {
        console.warn('[hotkey] unregister failed:', error && error.message);
      }
    }
    current = next;
    held = false;
    if (next === '') {
      report({ registered: null, error: null });
      return;
    }
    if (!isSafeAccelerator(next)) {
      report({ registered: false, error: REASON_UNSAFE });
      return;
    }
    try {
      const ok = globalShortcut.register(next, () => onFire());
      held = ok === true;
      report(ok ? { registered: true, error: null } : { registered: false, error: REASON_TAKEN });
    } catch (error) {
      report({ registered: false, error: REASON_INVALID });
    }
  }

  return {
    async refresh() {
      if (stopped) return false;
      let wanted = null;
      try {
        wanted = await readAccelerator();
      } catch (error) {
        console.warn('[hotkey] preference could not be read:', error && error.message);
      }
      if (stopped) return false;
      const read = typeof wanted === 'string';
      if (read) {
        if (store && wanted !== current) store.save(wanted);
      } else {
        wanted = current === null ? (store ? store.load() : null) : current;
      }
      if (typeof wanted !== 'string') return false;
      if (wanted !== current || !(held || current === '')) apply(wanted);
      return read;
    },
    stop() {
      stopped = true;
      try {
        if (current && held) globalShortcut.unregister(current);
      } catch (error) {
        console.warn('[hotkey] unregister failed:', error && error.message);
      }
    },
  };
}

module.exports = { DEFAULT_ACCELERATOR, createHotkey, acceleratorOf, readPreference, isSafeAccelerator };
