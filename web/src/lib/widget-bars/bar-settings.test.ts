/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { BAR_DEFAULTS, resolveBars, widgetBars } from './bar-settings.svelte';
import { DEFAULT_RAIL_ITEMS, RAIL_FIELD } from '../session-rail/rail-model';
import { railStores } from '../session-rail/rail-store.svelte';

type Write = { field: string; value: unknown };
const g = globalThis as Record<string, unknown>;
let writes: Write[];
let batches: string[][];
let statuses: string[];
let shared: Record<string, unknown>;
let listeners: ((value: unknown) => void)[];
let server: unknown;
let adopt: ReturnType<typeof vi.fn>;
let call: ReturnType<typeof vi.fn>;

beforeEach(() => {
  writes = [];
  batches = [];
  statuses = [];
  shared = {};
  listeners = [];
  server = null;
  adopt = vi.fn();
  call = vi.fn(async () => ({ status: 'committed', revision: 9, values: {} }));
  g.PreferenceBridge = {
    read: (field: string) => shared[field] ?? null,
    write: async (field: string, value: unknown) => {
      writes.push({ field, value });
      const status = statuses.shift() ?? 'committed';
      if (status === 'committed') shared[field] = value;
      return { status };
    },
    writeMany: async (entries: Write[]) => {
      batches.push(entries.map((e) => e.field));
      for (const { field, value } of entries) {
        writes.push({ field, value });
        shared[field] = value;
      }
      return { status: 'committed' };
    },
    follow: (_field: string, apply: (value: unknown) => void) => {
      listeners.push(apply);
      return () => {};
    },
  };
  g.Preferences = { committedValue: () => server, discardLocal: vi.fn(), adopt };
  g.API = { call };
  widgetBars.reload();
});
afterEach(() => {
  delete g.PreferenceBridge;
  delete g.Preferences;
  delete g.API;
});

describe('widgetBars', () => {
  test('absent reads as the defaults and writes nothing', () => {
    expect(widgetBars.stored).toBeNull();
    expect(widgetBars.view).toEqual(BAR_DEFAULTS);
    expect(resolveBars(undefined)).toEqual(BAR_DEFAULTS);
    expect(writes).toEqual([]);
  });

  test('set writes only the leaf that changed', async () => {
    expect(await widgetBars.set('side', { size: 'compact' })).toBe('committed');
    expect(writes).toEqual([{ field: 'widget_bars', value: { v: 1, side: { size: 'compact' } } }]);
    expect(widgetBars.view.side).toEqual({ show: true, size: 'compact', mode: 'pinned' });
    expect(widgetBars.view.bottom).toEqual(BAR_DEFAULTS.bottom);
  });

  test('a null leaf removes only that leaf; removing the last stored leaf writes null', async () => {
    await widgetBars.set('side', { size: 'compact', mode: 'pinned' });
    await widgetBars.set('side', { size: null });
    expect(writes[1]!.value).toEqual({ v: 1, side: { mode: 'pinned' } });
    await widgetBars.set('side', { mode: null });
    expect(writes[2]).toEqual({ field: 'widget_bars', value: null });
    expect(widgetBars.stored).toBeNull();
  });

  test('a 409 replays ONLY that op over the adopted server value, once', async () => {
    server = { v: 1, bottom: { size: 'detailed' } };
    statuses = ['stale_revision', 'committed'];
    expect(await widgetBars.set('side', { show: false })).toBe('replayed');
    expect(writes.map((w) => w.value)).toEqual([
      { v: 1, side: { show: false } },
      { v: 1, side: { show: false }, bottom: { size: 'detailed' } },
    ]);
  });

  test('a second 409 is a conflict: the server value stays and there is no third write', async () => {
    server = { v: 1, bottom: { size: 'detailed' } };
    statuses = ['stale_revision', 'stale_revision'];
    expect(await widgetBars.set('side', { show: false })).toBe('conflict');
    expect(writes).toHaveLength(2);
    expect(widgetBars.stored).toEqual({ v: 1, bottom: { size: 'detailed' } });
    expect(widgetBars.write).toBe('conflict');
  });

  test('a failed write puts the value back', async () => {
    statuses = ['failed'];
    expect(await widgetBars.set('side', { show: false })).toBe('failed');
    expect(widgetBars.stored).toBeNull();
  });

  test('setTogether sets and removes the leaf; the same value is unchanged and writes nothing', async () => {
    expect(await widgetBars.setTogether('one')).toBe('committed');
    expect(await widgetBars.setTogether('one')).toBe('unchanged');
    expect(await widgetBars.setTogether(null)).toBe('committed');
    expect(writes.map((w) => w.value)).toEqual([{ v: 1, together: 'one' }, null]);
  });

  test('following applies the pushed value without writing', () => {
    widgetBars.start(null);
    listeners[0]!({ v: 1, together: 'one', bottom: { mode: 'pinned', size: 'huge' } });
    expect(widgetBars.view.together).toBe('one');
    expect(widgetBars.view.bottom).toEqual({ show: true, size: 'cozy', mode: 'pinned' });
    expect(writes).toEqual([]);
  });

  test('reset posts the route once, adopts the body and re-reads', async () => {
    await widgetBars.set('side', { show: false });
    shared = {};
    expect(await widgetBars.reset()).toBe('committed');
    expect(call).toHaveBeenCalledTimes(1);
    expect(call).toHaveBeenCalledWith('/preferences/widget-bars/reset', { method: 'POST' });
    expect(adopt).toHaveBeenCalledWith({ status: 'committed', revision: 9, values: {} });
    expect(widgetBars.stored).toBeNull();
  });

  test('reset reloads both rail stores', async () => {
    const side = vi.spyOn(railStores.side, 'reload');
    const bottom = vi.spyOn(railStores.bottom, 'reload');
    await widgetBars.reset();
    expect(side).toHaveBeenCalledTimes(1);
    expect(bottom).toHaveBeenCalledTimes(1);
    side.mockRestore();
    bottom.mockRestore();
  });

  test('reset reports unchanged when the route says so, failed when the call throws', async () => {
    call.mockResolvedValueOnce({ status: 'unchanged', revision: 9, values: {} });
    expect(await widgetBars.reset()).toBe('unchanged');
    call.mockRejectedValueOnce(new Error('boom'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(await widgetBars.reset()).toBe('failed');
    warn.mockRestore();
  });

  test('customized is true when the field or either rail is present', () => {
    expect(widgetBars.customized).toBe(false);
    railStores.bottom.stored = { sections: [[{ widget: 'core.notes', look: null }]], ratio: 0.5 };
    expect(widgetBars.customized).toBe(true);
    expect(widgetBars.isDefault('bottom')).toBe(false);
    expect(widgetBars.isDefault('side')).toBe(true);
    railStores.bottom.stored = null;
  });
});

describe('rail defaults', () => {
  test('the side rail default is files, notes then bookmarks', () => {
    expect(DEFAULT_RAIL_ITEMS.map((i) => i.widget)).toEqual(['core.files', 'core.notes', 'core.bookmarks']);
  });
});

describe('the sidebar rail leaf (issue #1790)', () => {
  test('absent reads as auto-hide and writes nothing; the bars view is unchanged by it', () => {
    expect(widgetBars.rail.mode).toBe('autohide');
    expect(widgetBars.view).toEqual(BAR_DEFAULTS);
    expect(writes).toEqual([]);
  });

  test('setRail writes only the rail leaf, beside the bars\' leaves, and null removes it again', async () => {
    await widgetBars.set('side', { size: 'compact' });
    expect(await widgetBars.setRail('pinned')).toBe('committed');
    expect(writes.at(-1)).toEqual({ field: 'widget_bars', value: { v: 1, side: { size: 'compact' }, rail: { mode: 'pinned' } } });
    expect(widgetBars.rail.mode).toBe('pinned');
    expect(await widgetBars.setRail(null)).toBe('committed');
    expect(writes.at(-1)).toEqual({ field: 'widget_bars', value: { v: 1, side: { size: 'compact' } } });
    expect(await widgetBars.setRail(null), 'nothing to remove').toBe('unchanged');
  });

  test('a rail leaf alone is a whole value, and a malformed one is dropped, never guessed', async () => {
    await widgetBars.setRail('pinned');
    expect(widgetBars.stored).toEqual({ v: 1, rail: { mode: 'pinned' } });
    shared['widget_bars'] = { v: 1, rail: { mode: 'float' } };
    widgetBars.reload();
    expect(widgetBars.stored).toEqual({ v: 1 });
    expect(widgetBars.rail.mode).toBe('autohide');
  });
});
