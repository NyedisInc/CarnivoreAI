/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import TimeZonePanel from './TimeZonePanel.svelte';
import { DEFAULT_TIME_ZONE, filterZones, supportedZones } from './time-zone';

type G = { PreferenceBridge?: unknown };

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete (globalThis as G).PreferenceBridge;
});

function install(answer: unknown = { status: 'committed' }) {
  const state = { stored: undefined as unknown, writes: [] as unknown[], follow: null as null | ((v: unknown) => void) };
  (globalThis as G).PreferenceBridge = {
    read: (_f: string, local: () => unknown) => (state.stored !== undefined ? state.stored : local()),
    write: async (_f: string, value: unknown) => {
      state.writes.push(value);
      if ((answer as { status: string }).status === 'committed') state.stored = value;
      return answer;
    },
    follow: (_f: string, apply: (v: unknown) => void) => {
      state.follow = apply;
      return () => { state.follow = null; };
    },
  };
  return state;
}

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TimeZonePanel, { target }));
  flushSync();
  return target;
}

const radio = (root: HTMLElement, name: string) => root.querySelector(`input[data-time-zone-name="${name}"]`) as HTMLInputElement | null;

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
}

async function type(root: HTMLElement, text: string): Promise<void> {
  const box = root.querySelector('input[data-time-zone="search"]') as HTMLInputElement;
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
}

test('new york is checked when nothing is stored', () => {
  install();
  const root = render();
  expect(radio(root, DEFAULT_TIME_ZONE)?.checked).toBe(true);
  expect(root.querySelector('[data-time-zone="note"]')?.textContent).toContain('next run');
});

test('typing narrows the list and a miss says so', async () => {
  install();
  const root = render();
  await type(root, 'new york');
  expect(radio(root, 'America/New_York')).not.toBeNull();
  expect(radio(root, 'Europe/Paris')).toBeNull();
  await type(root, 'zzzz-nothing');
  expect(root.querySelector('[data-time-zone="none"]')).not.toBeNull();
});

test('picking a zone saves it once', async () => {
  const state = install();
  const root = render();
  await type(root, 'paris');
  radio(root, 'Europe/Paris')!.click();
  await settle();
  expect(state.writes).toEqual(['Europe/Paris']);
  expect(root.querySelector('[role="alert"]')).toBeNull();
  expect(root.querySelector('[data-time-zone="current"]')?.textContent).toContain('Europe/Paris');
});

test('a refused save puts the stored zone back and says why', async () => {
  const state = install({ status: 'refused', detail: 'not a zone this server knows' });
  const root = render();
  await type(root, 'paris');
  radio(root, 'Europe/Paris')!.click();
  await settle();
  expect(state.writes).toEqual(['Europe/Paris']);
  expect(root.querySelector('[data-time-zone="current"]')?.textContent).toContain(DEFAULT_TIME_ZONE);
  expect(root.querySelector('[role="alert"]')?.textContent).toContain('not a zone this server knows');
});

test('a change from another device moves the current zone', async () => {
  const state = install();
  const root = render();
  state.follow!('Asia/Tokyo');
  await settle();
  expect(root.querySelector('[data-time-zone="current"]')?.textContent).toContain('Asia/Tokyo');
});

test('the filter matches every word and the list always holds utc and new york', () => {
  expect(filterZones(['Europe/Paris', 'America/New_York'], 'america new')).toEqual(['America/New_York']);
  expect(filterZones(['Europe/Paris'], '  ')).toEqual(['Europe/Paris']);
  const all = supportedZones();
  expect(all).toContain('UTC');
  expect(all).toContain(DEFAULT_TIME_ZONE);
});
