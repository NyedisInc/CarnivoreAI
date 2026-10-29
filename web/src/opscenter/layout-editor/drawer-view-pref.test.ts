import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { setDrawerEnv } from '../../lib/drawer/env';
import { setViewClassSource, type ViewClass } from '../../lib/drawer/view-class';
import { resolveView, widgetDrawerView, VIEW_FIELD, VIEW_FIELD_MOBILE } from './drawer-view-pref.svelte';

let shared: Record<string, unknown>;
let writes: Array<[string, string]>;
let local: Record<string, string>;
let cls: ViewClass;

beforeEach(() => {
  shared = {};
  writes = [];
  local = {};
  cls = 'desktop';
  setViewClassSource(() => cls);
  setDrawerEnv({
    PreferenceBridge: {
      read: (field: string, fallback: () => unknown) => (field in shared ? shared[field] : fallback()),
      write: vi.fn(async (field: string, value: string, writeLocal: () => void) => {
        writeLocal();
        shared[field] = value;
        writes.push([field, value]);
      }),
    },
    localStorage: {
      getItem: (key: string) => local[key] ?? null,
      setItem: (key: string, value: string) => {
        local[key] = value;
      },
    },
  });
  widgetDrawerView.reset();
});

afterEach(() => {
  setDrawerEnv(null);
  setViewClassSource(null);
});

describe('the widget drawer view preference', () => {
  test('absent reads as the tree by type and nothing is written by reading', () => {
    expect(widgetDrawerView.mode).toBe('type');
    expect(writes).toEqual([]);
  });

  test('the desktop saves ui_preferences.widget_drawer_view', async () => {
    expect(widgetDrawerView.setMode('name')).toBe(true);
    await Promise.resolve();
    expect(writes).toEqual([[VIEW_FIELD, 'name']]);
    expect(widgetDrawerView.mode).toBe('name');
    expect(widgetDrawerView.setMode('name')).toBe(false);
  });

  test('the phone saves its own field and the desktop keeps its own', async () => {
    shared[VIEW_FIELD] = 'name';
    cls = 'mobile';
    widgetDrawerView.reset();
    expect(widgetDrawerView.mode).toBe('name');
    widgetDrawerView.setMode('type');
    await Promise.resolve();
    expect(writes).toEqual([[VIEW_FIELD_MOBILE, 'type']]);
    expect(resolveView('mobile')).toBe('type');
    expect(resolveView('desktop')).toBe('name');
  });

  test('a phone that never chose inherits the desktop; a stored value that is not a view is ignored', () => {
    shared[VIEW_FIELD] = 'name';
    expect(resolveView('mobile')).toBe('name');
    shared[VIEW_FIELD] = 'carousel';
    expect(resolveView('desktop')).toBe('type');
  });
});
