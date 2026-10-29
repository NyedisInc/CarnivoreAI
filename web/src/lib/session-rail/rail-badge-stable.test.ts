/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { fakeBadge, fakeListing } from './test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  const { fakeListing: listing } = await import('./test-support.svelte');
  return { ...real, sessions: listing, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../item-settings/store.svelte', () => ({ widgetSetting: () => true, isWidgetDisabled: () => false }));

import ZoneBadge from '../zone-shell/ZoneBadge.svelte';
import { registerAlertCount } from './alert-counts';
import type { WidgetManifest } from '../../opscenter/widgets/types';

const manifest = { id: 'test.blink', scope: 'session' } as unknown as WidgetManifest;
let handle: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

test('a listing refresh keeps the hold and the same bubble node, and a new count updates it in place', () => {
  let holds = 0;
  let releases = 0;
  fakeBadge.count = 5;
  registerAlertCount('test.blink', {
    hold: () => { holds += 1; return () => { releases += 1; }; },
    read: () => fakeBadge.count,
  });
  handle = mount(ZoneBadge, { target: document.body, props: { manifest } });
  flushSync();
  const bubble = document.querySelector('[data-rail-badge]');
  expect(bubble?.textContent).toBe('5');
  expect(holds).toBe(1);

  fakeListing.data = [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }];
  flushSync();
  expect(holds).toBe(1);
  expect(releases).toBe(0);
  expect(document.querySelector('[data-rail-badge]')).toBe(bubble);

  fakeBadge.count = 6;
  flushSync();
  expect(document.querySelector('[data-rail-badge]')).toBe(bubble);
  expect(bubble?.textContent).toBe('6');
});
