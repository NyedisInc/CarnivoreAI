/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import LogToolbar from './LogToolbar.svelte';
import { emptyFilter } from './filter';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');
const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

function draw(expires_at: string | null): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  const level = { level: expires_at ? 'debug' : 'info', source: 'env' as const, env_level: 'info',
    choices: ['error', 'warn', 'info', 'debug'], expires_at };
  mounted.push(mount(LogToolbar, { target, props: { filter: emptyFilter(), sources: [], patternError: null, level, levelBusy: false,
    onFilter: () => {}, onLevel: () => {}, onExport: () => {}, onClear: () => {} } }));
  flushSync();
  return target;
}

test('a temporary debug shows debug selected and "debug until HH:MM"', () => {
  const root = draw(new Date(Date.now() + 600_000).toISOString());
  expect(root.querySelector<HTMLSelectElement>('[data-log-server-level]')!.value).toBe('debug');
  expect(root.querySelector('[data-log-server-level-until]')!.textContent).toMatch(/debug until \d\d:\d\d/);
});

test('with nothing pending the env choice is selected and no until text shows', () => {
  const root = draw(null);
  expect(root.querySelector<HTMLSelectElement>('[data-log-server-level]')!.value).toBe('');
  expect(root.querySelector('[data-log-server-level-until]')).toBeNull();
});
