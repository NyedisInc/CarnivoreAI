/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ALL_FILTERS_ON } from './model';
import {
  TIMELINE_FILTERS_PREF_FIELD,
  TIMELINE_FILTERS_STORAGE_KEY,
  startTimelineFiltersSync,
  syncTimelineFiltersFromPreferences,
  timelineFilters,
} from './filters.svelte';

beforeEach(() => {
  localStorage.clear();
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  delete (globalThis as Record<string, unknown>).Preferences;
  timelineFilters.reset();
});

afterEach(() => {
  localStorage.clear();
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  delete (globalThis as Record<string, unknown>).Preferences;
  timelineFilters.reset();
});

describe('timelineFilters sync via ui_preferences.timeline_filters (#3385)', () => {
  test('hydrates from ui_preferences, writes through on toggle, and follows live preferences.changed without echo', () => {
    let remoteHandler: ((value: unknown) => void) | null = null;
    let shared: unknown = { ...ALL_FILTERS_ON, sleeps: false };
    const writeSpy = vi.fn(async (_field: string, value: unknown, local: () => void) => {
      local();
      shared = value;
      return { status: 'committed' };
    });
    const unsubSpy = vi.fn();

    (globalThis as Record<string, unknown>).PreferenceBridge = {
      read: (field: string, fallback: () => unknown) => (field === TIMELINE_FILTERS_PREF_FIELD ? shared : fallback()),
      write: writeSpy,
      follow: (field: string, apply: (value: unknown) => void) => {
        if (field === TIMELINE_FILTERS_PREF_FIELD) remoteHandler = apply;
        return unsubSpy;
      },
    };

    const stop = startTimelineFiltersSync(null);
    expect(timelineFilters.value).toEqual({ ...ALL_FILTERS_ON, sleeps: false });
    expect(JSON.parse(localStorage.getItem(TIMELINE_FILTERS_STORAGE_KEY) ?? '{}')).toEqual({ ...ALL_FILTERS_ON, sleeps: false });
    expect(writeSpy).not.toHaveBeenCalled();

    timelineFilters.toggle('bookmarks');
    expect(timelineFilters.value.bookmarks).toBe(false);
    expect(writeSpy).toHaveBeenCalledTimes(1);
    expect(writeSpy).toHaveBeenCalledWith(
      TIMELINE_FILTERS_PREF_FIELD,
      { ...ALL_FILTERS_ON, sleeps: false, bookmarks: false },
      expect.any(Function),
    );
    expect(JSON.parse(localStorage.getItem(TIMELINE_FILTERS_STORAGE_KEY) ?? '{}')).toEqual({
      ...ALL_FILTERS_ON,
      sleeps: false,
      bookmarks: false,
    });

    remoteHandler!({ ...ALL_FILTERS_ON, restarts: false });
    expect(timelineFilters.value).toEqual({ ...ALL_FILTERS_ON, restarts: false });
    expect(JSON.parse(localStorage.getItem(TIMELINE_FILTERS_STORAGE_KEY) ?? '{}')).toEqual({
      ...ALL_FILTERS_ON,
      restarts: false,
    });
    expect(writeSpy).toHaveBeenCalledTimes(1);

    shared = null;
    syncTimelineFiltersFromPreferences();
    remoteHandler!(null);
    remoteHandler!({});
    expect(timelineFilters.value).toEqual({ ...ALL_FILTERS_ON, restarts: false });

    stop();
    expect(unsubSpy).toHaveBeenCalledTimes(1);
  });
});
