/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const hoisted = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../../api/auth.svelte', () => ({ authFetch: hoisted.authFetch, ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/noc-feed.svelte', () => ({ live: {}, watchLive: () => () => {} }));

import Controls from './Controls.svelte';
import { analytics } from './state.svelte';
import { dimensionValues } from './api';
import { clockLabel } from './value-format';
import { seriesBody } from '../../viz/plan';
import type { ChartConfig, QueryResult } from './types';

const config: ChartConfig = { revision: 1, id: 'c1', title: 't', enabled: true, filters: {}, range: { mode: 'global' }, display: { type: 'line' }, series: [{ metric: 'total_tokens', operation: 'timeline' }] };
const ctx = { now: Date.parse('2026-10-12T12:00:00Z'), timezone: 'UTC', filters: {} };
const range = { from: '2026-10-11T12:00:00Z', to: '2026-10-12T12:00:00Z' };

afterEach(() => { document.body.innerHTML = ''; hoisted.authFetch.mockReset(); analytics.dimensions = {}; analytics.filters = {}; });

describe('the Pack scope on the wire', () => {
  test('a usage series asks for the whole Pack and a quota series does not', () => {
    expect(seriesBody(config, config.series[0]!, range, ctx).scope).toBe('pack');
    const quota = { metric: 'quota_utilization', operation: 'timeline' as const, group_by: 'account_id' };
    expect(seriesBody(config, quota, range, ctx).scope).toBeUndefined();
  });

  test('the computer filter rides along on a usage series and is dropped from a quota series', () => {
    const filtered = { ...ctx, filters: { host: 'install-studio' } };
    expect(seriesBody(config, config.series[0]!, range, filtered).filters).toEqual({ host: 'install-studio' });
    expect(seriesBody(config, { metric: 'quota_utilization', operation: 'timeline' }, range, filtered).filters).toEqual({});
  });
});

describe('a saved chart does not erase the computer filter', () => {
  test('the null filters the server stores on a chart and its series never override a set computer', () => {
    const nulls = { host: null, provider: null, model: null } as unknown as ChartConfig['filters'];
    const saved = { ...config, filters: nulls, series: [{ ...config.series[0]!, filters: nulls }] };
    expect(seriesBody(saved, saved.series[0]!, range, { ...ctx, filters: { host: 'install-studio' } }).filters).toEqual({ host: 'install-studio' });
    const own = { ...saved, filters: { ...nulls, host: 'local' } } as ChartConfig;
    expect(seriesBody(own, own.series[0]!, range, ctx).filters).toEqual({ host: 'local' });
  });
});

describe('the computer select', () => {
  test('lists this computer and the peers from the dimension and sets the filter', () => {
    analytics.dimensions = { host: [
      { key: 'local', label: 'mac', filter_value: 'local' },
      { key: 'install-studio', label: 'studio through 14:05', filter_value: 'install-studio' },
    ] };
    const target = document.createElement('div');
    document.body.append(target);
    const view = mount(Controls, { target });
    flushSync();
    const selects = [...target.querySelectorAll('select')];
    const host = selects.find((select) => [...select.options].some((option) => option.value === 'install-studio'));
    expect(host).toBeTruthy();
    expect([...host!.options].map((option) => [option.value, option.textContent])).toEqual([['', 'all'], ['local', 'mac'], ['install-studio', 'studio through 14:05']]);
    expect(host!.closest('label')?.textContent).toContain('computer');
    host!.value = 'install-studio';
    host!.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    expect(analytics.filters.host).toBe('install-studio');
    unmount(view);
  });
});

describe('an offline computer', () => {
  test('its dimension entry reads "<computer> through <time>"', async () => {
    hoisted.authFetch.mockResolvedValue({ items: [
      { key: 'local', label: 'mac', filter_value: 'local' },
      { key: 'install-studio', label: 'studio', filter_value: 'install-studio', through: '2026-10-12T14:05:00Z' },
    ] });
    const items = await dimensionValues('host', range.from, range.to);
    expect(items.map((item) => item.label)).toEqual(['mac', `studio through ${clockLabel('2026-10-12T14:05:00Z')}`]);
  });
});
