/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

globalThis.ResizeObserver ??= class { observe(): void {} unobserve(): void {} disconnect(): void {} } as unknown as typeof ResizeObserver;

const reads: string[] = [];
const rec = (id: number, level: string, event: string, extra: Record<string, unknown> = {}) => ({
  id: `7-${id}`, timestamp: `2026-10-15T19:00:0${id}Z`, level, source: 'server', event, fields: {}, lines: [], dropped_lines: 0,
  traceback: false, continues: false, approx_time: false, ...extra,
});
const ALL = [
  rec(1, 'error', 'boom', { fields: { session: 'ses_1' }, lines: ['Traceback (most recent call last):', 'KeyError: 1'], traceback: true }),
  rec(2, 'warn', 'careful', { approx_time: true }),
  rec(3, 'info', 'fine', { fields: { session: 'ses_2' } }),
  rec(4, 'debug', 'chatty'),
];

vi.mock('../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string) => {
    reads.push(path);
    if (path.startsWith('/log-level')) return { level: 'info', source: 'env', env_level: 'info', choices: ['error', 'warn', 'info', 'debug'], expires_at: null };
    return { records: path.includes('since=') ? [] : ALL, head: '7-400', before: null, gap: false, reset: false, levels: [] };
  },
}));
vi.mock('../api/events.svelte', () => ({ subscribe: () => () => {} }));

import DeveloperLog from '../cells/developer/LogViewer.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import { META } from '../engine/meta';
import { LOG_LEVELS, LOG_LEVELS_KEY, readLevels, toggleLevel, writeLevels } from './log-levels';

setLocale('en');
const apps: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  reads.length = 0;
  globalThis.localStorage?.clear();
});

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i += 1) {
    await Promise.resolve();
    await tick();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  await new Promise((resolve) => setTimeout(resolve, 300));
  flushSync();
}

async function render(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(DeveloperLog, { target, props: { width: 600, height: 300, meta: META['developer'], instance: 'developer', page: 'home' } as never }));
  await settle();
  return target;
}

const events = (target: HTMLElement): string[] => [...target.querySelectorAll('[data-log-row] .oc-lv-event')].map((n) => n.textContent ?? '');
const pressed = (target: HTMLElement): string[] =>
  [...target.querySelectorAll('[data-log-levels] button')].filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.getAttribute('data-level') as string);

describe('the log viewer', () => {
  test('reads v2 records, opens on the error level only, oldest to newest; the tag says the level; a traceback is marked', async () => {
    const target = await render();
    expect(reads.some((r) => r.startsWith('/server-log?v=2'))).toBe(true);
    expect(pressed(target)).toEqual(['error']);
    expect(events(target)).toEqual(['boom']);
    const first = target.querySelector('[data-log-row][data-level="error"]') as HTMLElement;
    expect(first.querySelector('.oc-lv-tag')?.textContent).toBe('error');
    expect(first.hasAttribute('data-traceback')).toBe(true);
    expect(first.querySelector('.oc-lv-more')?.textContent).toBe('+2 lines');
  });

  test('turning levels on shows their records and is remembered', async () => {
    const target = await render();
    (target.querySelector('[data-log-levels] [data-level="warn"]') as HTMLButtonElement).click();
    await settle();
    expect(pressed(target)).toEqual(['error', 'warn']);
    expect(events(target)).toEqual(['boom', 'careful']);
    expect(JSON.parse(globalThis.localStorage.getItem(LOG_LEVELS_KEY) as string)).toEqual(['error', 'warn']);
  });

  test('a field chip filters in on click and out on alt-click', async () => {
    writeLevels([...LOG_LEVELS]);
    const target = await render();
    (target.querySelector('[data-log-row] [data-log-field="session"]') as HTMLButtonElement).click();
    await settle();
    expect(events(target)).toEqual(['boom']);
    (target.querySelector('[data-log-chips] button') as HTMLButtonElement).click();
    await settle();
    expect(events(target)).toHaveLength(4);
    (target.querySelector('[data-log-row] [data-log-field="session"]') as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { altKey: true, bubbles: true }));
    await settle();
    expect(events(target)).toEqual(['careful', 'fine', 'chatty']);
  });

  test('expanding a record shows it as JSON with its traceback lines', async () => {
    const target = await render();
    (target.querySelector('[data-log-row] [data-log-expand]') as HTMLButtonElement).click();
    await settle();
    expect(JSON.parse(target.querySelector('[data-log-json]')?.textContent ?? '{}').session).toBe('ses_1');
    expect(target.querySelector('[data-log-lines]')?.textContent).toContain('KeyError: 1');
  });

  test('a record with no time of its own shows the borrowed time with a ~ and a muted style', async () => {
    writeLevels([...LOG_LEVELS]);
    const target = await render();
    const times = [...target.querySelectorAll('[data-log-row] .oc-lv-time')];
    expect(times.map((n) => n.textContent)).toEqual(['19:00:01', '~19:00:02', '19:00:03', '19:00:04']);
    expect(times.map((n) => n.hasAttribute('data-log-time-approx'))).toEqual([false, true, false, false]);
    expect(times[1]?.classList.contains('oc-lv-time--approx')).toBe(true);
    expect(times[1]?.getAttribute('title')).toBe('no time of its own: the nearest earlier line\'s time');
  });

  test('every level off says so and draws no records', async () => {
    writeLevels([]);
    const target = await render();
    expect(target.querySelector('[data-log-none]')?.textContent).toContain('every level is off');
    expect(events(target)).toEqual([]);
  });
});

describe('log-levels', () => {
  test('bad or missing storage falls back to the error level only', () => {
    expect(readLevels()).toEqual(['error']);
    globalThis.localStorage.setItem(LOG_LEVELS_KEY, '{nope');
    expect(readLevels()).toEqual(['error']);
    globalThis.localStorage.setItem(LOG_LEVELS_KEY, '["error","warn","info","debug"]');
    expect(readLevels()).toEqual([...LOG_LEVELS]);
    globalThis.localStorage.setItem(LOG_LEVELS_KEY, '["warn","bogus"]');
    expect(readLevels()).toEqual(['warn']);
  });

  test('toggleLevel keeps strip order', () => {
    expect(toggleLevel(['error', 'info'], 'warn')).toEqual(['error', 'warn', 'info']);
    expect(toggleLevel(['error', 'warn'], 'warn')).toEqual(['error']);
  });
});
