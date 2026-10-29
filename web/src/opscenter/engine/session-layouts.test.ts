/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { createLayoutStore } from './layout.svelte';
import { beginGesture } from './pointer';
import { PRIMARY_SLOT, resetLayout } from './model';
import { META } from './meta';
import { STORAGE_KEYS, flushSave, storageKey } from './persist';
import { bindPrimary, watchPrimaryBind, PRIMARY_BIND_EVENT } from './primary-bind';
import {
  MAX_SESSION_LAYOUTS,
  SESSION_INDEX_KEY,
  forgetSession,
  layoutKey,
  readIndex,
  touchSession,
} from './session-layouts';
import type { Layout } from './types';

function slots(layout: Layout): string[] {
  return layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  flushSave();
  localStorage.clear();
});

describe('one layout per session', () => {
  test('A -> B -> A: B shows only its terminal, and A gets its component back', () => {
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a');
    expect(store.add('terminal', 'ses_x')).toBeNull();
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);

    store.bindSession('cloude_b');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);

    store.bindSession('cloude_a');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);
  });

  test("a component added on B stays on B and never appears on A", () => {
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a');
    store.bindSession('cloude_b');
    store.show('notes');
    expect(slots(store.state.layout)).toContain('notes');
    store.bindSession('cloude_a');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
    store.bindSession('cloude_b');
    expect(slots(store.state.layout)).toContain('notes');
  });

  test('a fresh store (a reload) reads each session back from storage', () => {
    const first = createLayoutStore('terminal');
    first.bindSession('cloude_a');
    first.add('terminal', 'ses_x');
    flushSave();
    const reloaded = createLayoutStore('terminal');
    expect(slots(reloaded.state.layout)).toEqual([PRIMARY_SLOT]);
    reloaded.bindSession('cloude_a');
    expect(slots(reloaded.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);
  });

  test('removing the last component leaves the terminal and stores nothing', () => {
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a');
    store.add('terminal', 'ses_x');
    flushSave();
    expect(localStorage.getItem(storageKey('terminal', 'cloude_a'))).not.toBeNull();
    store.remove('terminal:ses_x');
    flushSave();
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
    expect(localStorage.getItem(storageKey('terminal', 'cloude_a'))).toBeNull();
    expect(readIndex()).not.toContain('cloude_a');
  });

  test('an unbound surface writes nothing under any key', () => {
    const store = createLayoutStore('terminal');
    store.add('terminal', 'ses_x');
    flushSave();
    expect(Object.keys(localStorage).filter((key) => key.includes('opscenter'))).toEqual([]);
  });
});

describe('the old single layout', () => {
  test('migrates to the first session bound, and only to it', () => {
    const legacy = resetLayout(META, 'terminal');
    legacy.rows[0]!.slots = [
      { id: PRIMARY_SLOT, fr: 0.5 },
      { id: 'terminal:ses_x', fr: 0.5 },
    ];
    localStorage.setItem(STORAGE_KEYS.terminal, JSON.stringify(legacy));
    const store = createLayoutStore('terminal');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);

    store.bindSession('cloude_a');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);
    expect(localStorage.getItem(STORAGE_KEYS.terminal)).toBeNull();
    expect(localStorage.getItem(storageKey('terminal', 'cloude_a'))).not.toBeNull();

    store.bindSession('cloude_b');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
  });
});

describe('storage stays bounded', () => {
  test('past the cap, the least recently used session layout is removed', () => {
    for (let at = 0; at <= MAX_SESSION_LAYOUTS; at += 1) {
      localStorage.setItem(storageKey('terminal', `s${at}`), '{}');
      touchSession(`s${at}`);
    }
    const index = readIndex();
    expect(index).toHaveLength(MAX_SESSION_LAYOUTS);
    expect(index[0]).toBe(`s${MAX_SESSION_LAYOUTS}`);
    expect(index).not.toContain('s0');
    expect(localStorage.getItem(storageKey('terminal', 's0'))).toBeNull();
    expect(localStorage.getItem(storageKey('terminal', 's1'))).not.toBeNull();
  });

  test('forgetting a session drops its entry and its index line', () => {
    localStorage.setItem(storageKey('terminal', 'gone'), '{}');
    touchSession('gone');
    forgetSession('gone');
    expect(localStorage.getItem(storageKey('terminal', 'gone'))).toBeNull();
    expect(localStorage.getItem(SESSION_INDEX_KEY)).toBeNull();
  });
});

describe('the pane binding a session swaps the layout', () => {
  test('the bind event carries the tmux name and the surface follows it', () => {
    const store = createLayoutStore('terminal');
    const target = new EventTarget();
    const stop = watchPrimaryBind(store, target);
    target.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a', tmuxName: 'cloude_a' } }));
    expect(store.session).toBe('cloude_a');
    store.add('terminal', 'ses_b');
    target.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_b', tmuxName: 'cloude_b' } }));
    expect(store.session).toBe('cloude_b');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
    stop();
  });

  test("a viewer of the bound session inside its OWN layout is taken down after the swap", () => {
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a');
    store.add('terminal', 'ses_b');
    flushSave();
    store.bindSession('cloude_z');
    const own = resetLayout(META, 'terminal');
    own.rows[0]!.slots = [
      { id: PRIMARY_SLOT, fr: 0.5 },
      { id: 'terminal:ses_b', fr: 0.5 },
    ];
    localStorage.setItem(storageKey('terminal', 'cloude_b'), JSON.stringify(own));
    expect(bindPrimary(store, 'ses_b', 'cloude_b')).toBe(1);
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
    store.bindSession('cloude_a');
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_b']);
  });
});

describe('a gesture from the previous session writes nothing into the new one', () => {
  function twoCells(store: ReturnType<typeof createLayoutStore>): void {
    store.bindSession('cloude_a');
    expect(store.add('terminal', 'ses_x')).toBeNull();
  }

  test("a stale snapshot's move and restore are refused under B", () => {
    const store = createLayoutStore('terminal');
    twoCells(store);
    const held = store.snapshot();
    store.bindSession('cloude_b');
    store.dragColumns(held, 'r1', 0, 40, 1000, 100, 900);
    store.restore(held);
    flushSave();
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
    expect(localStorage.getItem(storageKey('terminal', 'cloude_b'))).toBeNull();
    store.bindSession('cloude_c');
    store.restore(held);
    flushSave();
    expect(localStorage.getItem(storageKey('terminal', 'cloude_c'))).toBeNull();
  });

  test('the swap ends the running gesture without its cancel, and frees the lock', () => {
    const store = createLayoutStore('terminal');
    twoCells(store);
    const handle = document.createElement('div');
    document.body.appendChild(handle);
    const down = new MouseEvent('pointerdown', { clientX: 0, clientY: 0, button: 0 });
    Object.defineProperty(down, 'pointerId', { value: 7 });
    Object.defineProperty(down, 'pointerType', { value: 'mouse' });
    const held = store.snapshot();
    let cancelled = 0;
    expect(
      beginGesture(handle, down as PointerEvent, {
        onMove: () => {},
        onCancel: () => {
          cancelled += 1;
          store.restore(held);
        },
      }),
    ).toBe(true);
    store.bindSession('cloude_b');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSave();
    expect(cancelled).toBe(0);
    expect(localStorage.getItem(storageKey('terminal', 'cloude_b'))).toBeNull();
    expect(beginGesture(handle, down as PointerEvent, { onMove: () => {} })).toBe(true);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    handle.remove();
  });
});

describe('a reused tmux name is a new session', () => {
  test('a new epoch under the same name starts clean', () => {
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a', 100);
    expect(store.add('terminal', 'ses_x')).toBeNull();
    store.bindSession('cloude_b', 1);
    store.bindSession('cloude_a', 200);
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
  });

  test('the same epoch (a restart, a re-adopt, a reload) keeps its layout', () => {
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a', 100);
    store.add('terminal', 'ses_x');
    store.bindSession('cloude_b', 1);
    store.bindSession('cloude_a', 100);
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);
    flushSave();
    const reloaded = createLayoutStore('terminal');
    reloaded.bindSession('cloude_a', 100);
    expect(slots(reloaded.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);
    expect(localStorage.getItem(storageKey('terminal', layoutKey('cloude_a', 100)))).not.toBeNull();
  });

  test('a name-only entry is adopted once, by the first bind with an epoch', () => {
    const named = resetLayout(META, 'terminal');
    named.rows[0]!.slots = [
      { id: PRIMARY_SLOT, fr: 0.5 },
      { id: 'terminal:ses_x', fr: 0.5 },
    ];
    localStorage.setItem(storageKey('terminal', 'cloude_a'), JSON.stringify(named));
    touchSession('cloude_a');
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a', 100);
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);
    expect(localStorage.getItem(storageKey('terminal', 'cloude_a'))).toBeNull();
    expect(localStorage.getItem(storageKey('terminal', layoutKey('cloude_a', 100)))).not.toBeNull();
    expect(readIndex()).toEqual([layoutKey('cloude_a', 100)]);
    store.bindSession('cloude_a', 200);
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
    store.bindSession('cloude_a', 100);
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_x']);
  });

  test('an unknown epoch falls back to the name alone and never guesses', () => {
    const store = createLayoutStore('terminal');
    store.bindSession('cloude_a', 100);
    store.add('terminal', 'ses_x');
    store.bindSession('cloude_a', null);
    expect(slots(store.state.layout)).toEqual([PRIMARY_SLOT]);
    store.show('notes');
    flushSave();
    expect(localStorage.getItem(storageKey('terminal', 'cloude_a'))).not.toBeNull();
    store.bindSession('cloude_b');
    store.bindSession('cloude_a');
    expect(slots(store.state.layout)).toContain('notes');
    expect(slots(store.state.layout)).not.toContain('terminal:ses_x');
  });

  test('the bind event carries the epoch through to the key', () => {
    const store = createLayoutStore('terminal');
    const target = new EventTarget();
    const stop = watchPrimaryBind(store, target);
    const bind = (tmuxEpoch: unknown): void => {
      target.dispatchEvent(
        new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a', tmuxName: 'cloude_a', tmuxEpoch } }),
      );
    };
    bind(100);
    expect(store.session).toBe(layoutKey('cloude_a', 100));
    bind('100');
    expect(store.session).toBe('cloude_a');
    bind(null);
    expect(store.session).toBe('cloude_a');
    stop();
  });
});
