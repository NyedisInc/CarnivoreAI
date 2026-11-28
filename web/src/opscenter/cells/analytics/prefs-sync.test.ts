/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const hoisted = vi.hoisted(() => ({
  createChart: vi.fn(async (chart: ChartConfig) => ({ ...chart, revision: 1 })),
  updateChart: vi.fn(async (chart: ChartConfig) => ({ ...chart, revision: chart.revision + 1 })),
  selfId: { value: null as string | null },
}));

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  createChart: hoisted.createChart,
  updateChart: hoisted.updateChart,
}));
vi.mock('./host-id.svelte', () => ({ selfHostInstallId: () => hoisted.selfId.value }));
vi.mock('../../viz/noc-feed.svelte', () => ({ live: {}, watchLive: () => () => {} }));
vi.mock('../../api/auth.svelte', () => ({
  authFetch: vi.fn(async () => ({})),
  ApiError: class extends Error { status = 0; },
  auth: { state: 'signed-in' },
}));

import {
  ANALYTICS_FILTERS_PREF_FIELD,
  ANALYTICS_PREF_WRITE_DELAY_MS,
  ANALYTICS_TIMEZONE_PREF_FIELD,
  analytics,
  resetAnalyticsPrefsSync,
  seedHomeAnalytics,
  setAnalyticsFilter,
  setAnalyticsTimezone,
  startAnalyticsPrefsSync,
  syncAnalyticsPrefsFromPreferences,
} from './state.svelte';
import { setWidgetFilter } from './chart-view';
import Controls from './Controls.svelte';
import { createLayoutStore } from '../../engine/layout.svelte';
import { seedControl } from '../../engine/home-seed';
import {
  displayHostFilterValue,
  explicitHostId,
  matchesHostFilter,
  normalizeHostFiltersForSave,
  seriesBody,
} from '../../viz/plan';
import type { ChartConfig } from './types';

const sampleChart = (id = 'synced-1'): ChartConfig => ({
  id,
  revision: 1,
  title: 'Synced tokens',
  enabled: true,
  series: [{ metric: 'total_tokens', operation: 'timeline' }],
  filters: {},
  range: { mode: 'global' },
  display: { type: 'line', legend: true },
  viz: 'timeline',
  options: {},
});

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  hoisted.createChart.mockClear();
  hoisted.updateChart.mockClear();
  hoisted.selfId.value = null;
  seedControl.reset();
  resetAnalyticsPrefsSync();
  analytics.charts = {};
  analytics.filters = {};
  analytics.dimensions = {};
  analytics.timezone = 'UTC';
  analytics.error = '';
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  delete (globalThis as Record<string, unknown>).Preferences;
});

afterEach(() => {
  resetAnalyticsPrefsSync();
  seedControl.reset();
  document.body.innerHTML = '';
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  delete (globalThis as Record<string, unknown>).Preferences;
  localStorage.clear();
  vi.useRealTimers();
});

describe('Pack-aware seedHomeAnalytics (#3385)', () => {
  test('skips seeding when GET /stats/charts already returned synced charts from Alpha', async () => {
    analytics.charts = { 'alpha-chart-1': sampleChart('alpha-chart-1') };
    const store = createLayoutStore('home');
    await seedHomeAnalytics(store);
    expect(hoisted.createChart).not.toHaveBeenCalled();
  });

  test('skips seeding when home_layout already carries synced boards', async () => {
    seedControl.attach(() => {}, () => new Set(), () => true);
    seedControl.markReady();
    const store = createLayoutStore('home');
    await seedHomeAnalytics(store);
    expect(hoisted.createChart).not.toHaveBeenCalled();
  });
});

describe('analytics.filters and analytics.timezone sync via ui_preferences (#3385)', () => {
  test('hydrates from ui_preferences, debounce-writes user edits, and follows live preferences.changed without echo', async () => {
    const handlers: Record<string, (value: unknown) => void> = {};
    const shared: Record<string, unknown> = {
      [ANALYTICS_FILTERS_PREF_FIELD]: { provider: 'claude', model: 'sonnet' },
      [ANALYTICS_TIMEZONE_PREF_FIELD]: 'America/New_York',
    };
    const writeSpy = vi.fn(async (field: string, value: unknown) => {
      shared[field] = value;
      return { status: 'committed' };
    });
    const unsubSpy = vi.fn();

    (globalThis as Record<string, unknown>).PreferenceBridge = {
      read: (field: string, fallback: () => unknown) => (field in shared ? shared[field] : fallback()),
      write: writeSpy,
      follow: (field: string, apply: (value: unknown) => void) => {
        handlers[field] = apply;
        return unsubSpy;
      },
    };

    const stop = startAnalyticsPrefsSync(null);
    expect(analytics.filters).toEqual({ provider: 'claude', model: 'sonnet' });
    expect(analytics.timezone).toBe('America/New_York');
    expect(writeSpy).not.toHaveBeenCalled();

    setAnalyticsFilter('provider', 'codex');
    setAnalyticsFilter('project', 'carnivore');
    setAnalyticsTimezone('Europe/London');
    expect(writeSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(ANALYTICS_PREF_WRITE_DELAY_MS + 20);
    expect(writeSpy).toHaveBeenCalledTimes(2);
    expect(writeSpy).toHaveBeenCalledWith(
      ANALYTICS_FILTERS_PREF_FIELD,
      { provider: 'codex', model: 'sonnet', project: 'carnivore' },
      expect.any(Function),
    );
    expect(writeSpy).toHaveBeenCalledWith(
      ANALYTICS_TIMEZONE_PREF_FIELD,
      'Europe/London',
      expect.any(Function),
    );

    handlers[ANALYTICS_FILTERS_PREF_FIELD]!({ host: 'iid-beta' });
    handlers[ANALYTICS_TIMEZONE_PREF_FIELD]!('UTC');
    await vi.advanceTimersByTimeAsync(ANALYTICS_PREF_WRITE_DELAY_MS * 2);
    expect(analytics.filters).toEqual({ host: 'iid-beta' });
    expect(analytics.timezone).toBe('UTC');
    expect(writeSpy).toHaveBeenCalledTimes(2);

    shared[ANALYTICS_FILTERS_PREF_FIELD] = null;
    shared[ANALYTICS_TIMEZONE_PREF_FIELD] = 'Not/A_Zone';
    syncAnalyticsPrefsFromPreferences();
    expect(analytics.filters).toEqual({ host: 'iid-beta' });
    expect(analytics.timezone).toBe('UTC');

    stop();
    expect(unsubSpy).toHaveBeenCalledTimes(2);
  });
});

describe('explicit install_id on host-filtered charts & controls (#3385)', () => {
  test('saves explicit self install_id instead of local on chart and global filters', async () => {
    hoisted.selfId.value = 'iid-alpha';
    const chart = sampleChart('c-host');
    analytics.charts = { [chart.id]: chart };

    setWidgetFilter(chart.id, 'host', 'local');
    expect(analytics.charts[chart.id]!.filters.host).toBe('iid-alpha');

    setAnalyticsFilter('host', 'local');
    expect(analytics.filters.host).toBe('iid-alpha');

    expect(explicitHostId('local', 'iid-alpha')).toBe('iid-alpha');
    expect(explicitHostId('iid-beta', 'iid-alpha')).toBe('iid-beta');
    expect(normalizeHostFiltersForSave({ host: 'local', hosts: ['local', 'iid-beta'] }, 'iid-alpha')).toEqual({
      host: 'iid-alpha',
      hosts: ['iid-alpha', 'iid-beta'],
    });
  });

  test('matches filters.host === selfInstallId cleanly on display and in plan.ts queries', () => {
    hoisted.selfId.value = 'iid-alpha';
    const hostItems = [
      { key: 'local', label: 'mac', filter_value: 'local' },
      { key: 'iid-beta', label: 'beta', filter_value: 'iid-beta' },
    ];
    expect(displayHostFilterValue('iid-alpha', hostItems, 'iid-alpha')).toBe('local');
    expect(displayHostFilterValue('iid-beta', hostItems, 'iid-alpha')).toBe('iid-beta');
    expect(matchesHostFilter(['iid-alpha'], 'local', 'iid-alpha')).toBe(true);
    expect(matchesHostFilter(['iid-beta'], 'local', 'iid-alpha')).toBe(false);

    analytics.dimensions = { host: hostItems };
    analytics.filters = { host: 'iid-alpha' };
    const target = document.createElement('div');
    document.body.append(target);
    const view = mount(Controls, { target });
    flushSync();
    const hostSelect = [...target.querySelectorAll('select')].find((el) => [...el.options].some((o) => o.value === 'iid-beta'));
    expect(hostSelect?.value).toBe('local');
    unmount(view);

    const cfg = { ...sampleChart('c-plan'), filters: { host: 'iid-alpha' } };
    const range = { from: '2026-10-11T12:00:00Z', to: '2026-10-12T12:00:00Z' };
    const localCtx = { now: Date.parse('2026-10-12T12:00:00Z'), timezone: 'UTC', filters: {}, selfInstallId: 'iid-alpha' };
    expect(seriesBody(cfg, cfg.series[0]!, range, localCtx).filters).toEqual({ host: 'local' });

    const peerCtx = { ...localCtx, selfInstallId: 'iid-beta' };
    expect(seriesBody(cfg, cfg.series[0]!, range, peerCtx).filters).toEqual({ host: 'iid-alpha' });
  });
});
