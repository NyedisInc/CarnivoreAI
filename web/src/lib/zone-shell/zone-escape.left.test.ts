/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async () => ({ v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [], machines: [] }),
}));

import { setLocale } from '../i18n/index.svelte';
import { widgetBars } from '../widget-bars/bar-settings.svelte';
import { activeFlyout } from '../sidebar-widgets/flyout.svelte';
import { RAIL_CONTAINER_ID } from '../sidebar-widgets/rail-dom';
import { SWARM_FLYOUT } from '../sidebar-widgets/widget-ids';
import { flyout, press, railBtn, railOn, setupRail, settle, teardownRail } from '../sidebar-widgets/fixtures/rail-harness';

setLocale('en');

const g = globalThis as Record<string, unknown>;
let shared: Record<string, unknown>;

beforeEach(async () => {
  shared = {};
  await setupRail();
  g.PreferenceBridge = {
    read: (field: string, fallback: () => unknown) => (field in shared ? shared[field] : fallback()),
    write: async (field: string, value: unknown, local: () => void) => { shared[field] = value; local(); return { status: 'committed' }; },
    follow: () => () => {},
  };
  widgetBars.reload();
});
afterEach(async () => {
  delete g.PreferenceBridge;
  widgetBars.reload();
  await teardownRail();
});

function escapeFrom(target: Element): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  flushSync();
  return event;
}

const stateOf = (): string | undefined => document.querySelector<HTMLElement>(`#${RAIL_CONTAINER_ID} .sbr-shell`)?.dataset['railState'];

test('an unpinned rail\'s slide-out hides on Escape from the main area or the document, never from a terminal', async () => {
  await railOn();
  const screen = document.createElement('div');
  screen.className = 'xterm';
  const term = document.createElement('textarea');
  screen.append(term);
  document.body.append(screen);

  await press(SWARM_FLYOUT);
  const fromTerminal = escapeFrom(term);
  await settle();
  expect(activeFlyout(), 'the terminal owns its Escape').toBe(SWARM_FLYOUT);
  expect(fromTerminal.defaultPrevented).toBe(false);

  for (const from of [document.getElementById('main-target')!, document.body]) {
    if (activeFlyout() !== SWARM_FLYOUT) await press(SWARM_FLYOUT);
    expect(activeFlyout()).toBe(SWARM_FLYOUT);
    const event = escapeFrom(from);
    await settle();
    expect(activeFlyout(), `Escape from ${from.tagName}#${from.id}`).toBeNull();
    expect(stateOf()).toBe('handle');
    expect(event.defaultPrevented).toBe(true);
  }
});

test('a pinned rail and its slide-out stay on an Escape from outside them', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  expect(stateOf()).toBe('pinned');
  await press(SWARM_FLYOUT);
  const event = escapeFrom(document.getElementById('main-target')!);
  await settle();
  expect(activeFlyout()).toBe(SWARM_FLYOUT);
  expect(stateOf()).toBe('pinned');
  expect(event.defaultPrevented, 'nothing to hide: the key is not claimed').toBe(false);
});

test('a pinned rail\'s slide-out keeps Escape from inside it, and from the rail key that opened it', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  await press(SWARM_FLYOUT);
  escapeFrom(flyout().querySelector<HTMLElement>('[data-flyout-close]')!);
  await settle();
  expect(activeFlyout(), 'Escape inside a pinned slide-out leaves it open').toBe(SWARM_FLYOUT);
  escapeFrom(railBtn(SWARM_FLYOUT));
  await settle();
  expect(activeFlyout(), 'so does Escape from its rail key').toBe(SWARM_FLYOUT);
  expect(stateOf()).toBe('pinned');
});

test('Escape from inside the slide-out closes it, however it was opened; an unpinned rail draws no key to press (#2047)', async () => {
  await railOn();
  await press(SWARM_FLYOUT);
  escapeFrom(flyout().querySelector<HTMLElement>('[data-flyout-close]')!);
  await settle();
  expect(activeFlyout()).toBeNull();
  expect(railBtn(SWARM_FLYOUT), 'no rail key while unpinned').toBeNull();
  await press(SWARM_FLYOUT);
  expect(activeFlyout()).toBe(SWARM_FLYOUT);
  escapeFrom(flyout().querySelector<HTMLElement>('[data-flyout-close]')!);
  await settle();
  expect(activeFlyout(), 'a reopened slide-out closes on Escape too').toBeNull();
});
