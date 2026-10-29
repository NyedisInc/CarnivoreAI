/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('../../viz/query-client', () => ({ runQueries: vi.fn(async (items: { metric: string; operation: string }[]) => items.map((item) => ({ ok: true, result: {
  metric: item.metric, operation: item.operation, unit: 'tokens', resolution: 'hour',
  series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value: 100 }] }],
  summary: { value: 100, samples: 3, contributing_conversations: 4 }, coverage: { minute_rows: 9 } } }))) }));
vi.mock('../../viz/visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));

import Cell from './Cell.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import { analytics } from './state.svelte';
import { tripwires } from '../../viz/tripwires.svelte';
import type { ChartConfig } from './types';
import type { SlotId } from '../../engine/types';

const TITLE = 'tokens by account';
let handle: Record<string, unknown> | null = null;
afterEach(() => { if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function framed(room: number, late = false): Promise<HTMLElement> {
  vi.stubGlobal('ResizeObserver', class { constructor(private cb: (entries: never) => void) {} observe() { queueMicrotask(() => this.cb([] as never)); } unobserve() {} disconnect() {} });
  const used: Record<string, number> = { full: 8, short: 3, none: 0 };
  const range = () => document.querySelector<HTMLElement>('.analytics-range')?.dataset.fit ?? 'none';
  const name = () => document.querySelector<HTMLElement>('.oc-frame-name');
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return this === name() ? Math.max(1, room - (used[range()] ?? 0)) : 100;
  });
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return this === name() ? (this.textContent ?? '').trim().length : 100;
  });
  const chart = { c1: { id: 'c1', revision: 1, title: TITLE, enabled: true, series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as unknown as ChartConfig };
  analytics.charts = late ? {} : chart;
  tripwires.list = [];
  const target = document.createElement('div');
  document.body.append(target);
  handle = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: Cell, width: 460, height: 320 } as never });
  for (let i = 0; i < 6; i += 1) { await new Promise((resolve) => setTimeout(resolve, 60)); await tick(); }
  if (late) {
    analytics.charts = chart;
    for (let i = 0; i < 6; i += 1) { await new Promise((resolve) => setTimeout(resolve, 60)); await tick(); }
  }
  flushSync();
  return target;
}

describe('the real card in the real frame', () => {
  test('wide: the name is the card title and the range label is in full', async () => {
    const target = await framed(80);
    expect(target.querySelector('.oc-frame-title h2.oc-frame-name')?.textContent?.trim()).toBe(TITLE);
    expect(target.querySelector<HTMLElement>('.analytics-range')?.dataset.fit).toBe('full');
  });
  test('a little narrower: the name is still the card title and the range label is shortened', async () => {
    const target = await framed(TITLE.length + used3());
    expect(target.querySelector('.oc-frame-title h2.oc-frame-name')?.textContent?.trim()).toBe(TITLE);
    expect(target.querySelector<HTMLElement>('.analytics-range')?.dataset.fit).toBe('short');
  });
  test('narrow: the name is the card title, the range label is dropped and rides in the name title attribute', async () => {
    const target = await framed(TITLE.length);
    const name = target.querySelector('.oc-frame-title h2.oc-frame-name');
    expect(name?.textContent?.trim()).toBe(TITLE);
    expect(target.querySelector<HTMLElement>('.analytics-range')?.dataset.fit).toBe('none');
    expect(name?.getAttribute('title')).toContain(TITLE);
  });
  test('narrow, the title arriving after the header is up: the range still gives way to it (staging g927529e)', async () => {
    const target = await framed(TITLE.length, true);
    expect(target.querySelector('.oc-frame-title h2.oc-frame-name')?.textContent?.trim()).toBe(TITLE);
    expect(target.querySelector<HTMLElement>('.analytics-range')?.dataset.fit).toBe('none');
  });
});

function used3(): number { return 3; }
