/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  addable,
  closeTab,
  layoutTabs,
  noteOpen,
  setTabs,
  startLayoutTabsSync,
  syncLayoutTabsFromPreferences,
  visibleTabs,
  withTab,
  LAYOUT_TABS_KEY,
  LAYOUT_TABS_PREF_FIELD,
} from './layout-tabs.svelte';

afterEach(() => {
  localStorage.clear();
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  delete (globalThis as Record<string, unknown>).Preferences;
  setTabs([]);
});

describe('layout tabs', () => {
  it('adds a tab once and appends it', () => {
    expect(withTab(['a'], 'b')).toEqual(['a', 'b']);
    expect(withTab(['a', 'b'], 'a')).toEqual(['a', 'b']);
  });

  it('offers only layouts not yet tabbed', () => {
    const all = [{ layout_uuid: 'a' }, { layout_uuid: 'b' }, { layout_uuid: 'c' }];
    expect(addable(all, ['a', 'c']).map((l) => l.layout_uuid)).toEqual(['b']);
  });

  it('closing the active tab names its neighbour, closing another names none', () => {
    expect(closeTab(['a', 'b', 'c'], 'b', 'b')).toEqual({ tabs: ['a', 'c'], open: 'c' });
    expect(closeTab(['a', 'b', 'c'], 'c', 'c')).toEqual({ tabs: ['a', 'b'], open: 'b' });
    expect(closeTab(['a', 'b', 'c'], 'a', 'b')).toEqual({ tabs: ['b', 'c'], open: null });
  });

  it('never closes the last tab', () => {
    expect(closeTab(['a'], 'a', 'a')).toEqual({ tabs: ['a'], open: null });
  });

  it('drops deleted layouts from view but keeps the active one', () => {
    expect(visibleTabs(['a', 'gone'], ['a'], 'a')).toEqual(['a']);
    expect(visibleTabs(['a', 'gone'], ['a'], 'gone')).toEqual(['a', 'gone']);
    expect(visibleTabs(['a', 'x'], null, 'a')).toEqual(['a', 'x']);
  });

  it('tabs an opened layout and persists the list', () => {
    setTabs([]);
    noteOpen('a');
    noteOpen('b');
    noteOpen('a');
    expect(layoutTabs.uuids).toEqual(['a', 'b']);
    expect(JSON.parse(localStorage.getItem(LAYOUT_TABS_KEY) ?? '[]')).toEqual(['a', 'b']);
  });

  it('mirrors setTabs to ui_preferences.layout_tabs and applies live preferences.changed without echoing (#3385)', () => {
    let remoteHandler: ((value: unknown) => void) | null = null;
    let shared: unknown = ['s1', 's2'];
    const writeSpy = vi.fn(async (_field: string, value: string[], local: () => void) => {
      local();
      shared = value;
      return { status: 'committed' };
    });
    const unsubSpy = vi.fn();
    (globalThis as Record<string, unknown>).PreferenceBridge = {
      read: (field: string, fallback: () => unknown) => (field === LAYOUT_TABS_PREF_FIELD ? shared : fallback()),
      write: writeSpy,
      follow: (field: string, apply: (value: unknown) => void) => {
        if (field === LAYOUT_TABS_PREF_FIELD) remoteHandler = apply;
        return unsubSpy;
      },
    };

    const stop = startLayoutTabsSync(null);
    expect(layoutTabs.uuids).toEqual(['s1', 's2']);
    expect(JSON.parse(localStorage.getItem(LAYOUT_TABS_KEY) ?? '[]')).toEqual(['s1', 's2']);
    expect(writeSpy).not.toHaveBeenCalled();

    noteOpen('s3');
    expect(layoutTabs.uuids).toEqual(['s1', 's2', 's3']);
    expect(writeSpy).toHaveBeenCalledTimes(1);
    expect(writeSpy).toHaveBeenCalledWith(LAYOUT_TABS_PREF_FIELD, ['s1', 's2', 's3'], expect.any(Function));

    remoteHandler!(['r1', 'r2']);
    expect(layoutTabs.uuids).toEqual(['r1', 'r2']);
    expect(JSON.parse(localStorage.getItem(LAYOUT_TABS_KEY) ?? '[]')).toEqual(['r1', 'r2']);
    expect(writeSpy).toHaveBeenCalledTimes(1);

    shared = undefined;
    syncLayoutTabsFromPreferences();
    remoteHandler!(null);
    expect(layoutTabs.uuids).toEqual(['r1', 'r2']);

    stop();
    expect(unsubSpy).toHaveBeenCalledTimes(1);
  });
});
