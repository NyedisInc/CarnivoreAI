/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({ status: 'ok' as const, data: null as LedgerSnapshot | null, fetchedAt: null as number | null, error: null as string | null }));
vi.mock('../../opscenter/api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), ledger: fakeLedger }));

import GlanceRow from './GlanceRow.svelte';
import './glances';
import { drawerZone } from './zone-store.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const HOUR = 3600_000;
const win = (kind: string, used: number, seconds: number) => ({ kind, label: kind, used_pct: used, window_seconds: seconds, resets_at: new Date(Date.now() + 4 * HOUR).toISOString() });
const account = { id: 'sam', name: 'sam', short_name: null, provider: 'claude', plan: 'max', identity: 'sam', credential_state: 'ok', fetched_at: null, next_poll_at: null, error: null, color: null, managed: false, windows: [win('five_hour', 30, 5 * 3600), win('seven_day', 40, 7 * 86400)] };

let instance: ReturnType<typeof mount> | null = null;
const placed: string[] = [];

function draw(widgets: string[], options = true): HTMLElement {
  const entries = widgets.map((widget) => {
    const key = drawerZone.addGlance(widget, true)!;
    placed.push(key);
    return { key, widget, manifest: CORE_MANIFESTS[widget]!, options: {} };
  });
  const host = document.createElement('div');
  document.body.append(host);
  instance = mount(GlanceRow, { target: host, props: { entries, onopen: () => {}, options } });
  flushSync();
  return host;
}

function press(el: Element, init: KeyboardEventInit): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
  el.dispatchEvent(event);
  flushSync();
  return event;
}

const openMenu = (): Element | null => document.querySelector('[role="menu"]');

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  fakeLedger.data = { accounts: [account], total: { accounts: 1, windows: [] }, loop: { alive: true, last_pass_at: null } } as unknown as LedgerSnapshot;
});

afterEach(() => {
  if (instance) unmount(instance);
  instance = null;
  for (const key of placed.splice(0)) drawerZone.removeGlance(key);
  document.body.replaceChildren();
});

test('Shift+F10 on a renderer tile\'s own button opens its placement menu; another key does not', () => {
  const host = draw(['core.ledger']);
  const tile = host.querySelector<HTMLElement>('.dz-glance[data-glance-tile] button')!;
  expect(tile, 'the provider renderer draws its tile').not.toBeNull();
  expect(press(tile, { key: 'ArrowRight' }).defaultPrevented).toBe(false);
  expect(openMenu(), 'an arrow is not the menu key').toBeNull();
  expect(press(tile, { key: 'F10', shiftKey: true }).defaultPrevented).toBe(true);
  expect(openMenu(), 'Shift+F10 opens the placement menu').not.toBeNull();
});

test('the menu key on the fallback tile opens its placement menu', () => {
  const host = draw(['core.keep-awake']);
  const tile = host.querySelector<HTMLElement>('button.dz-glance--icon')!;
  expect(press(tile, { key: 'ContextMenu' }).defaultPrevented).toBe(true);
  expect(openMenu()).not.toBeNull();
});

test('NEGATIVE: the harness row (no options) leaves the menu key alone and opens nothing', () => {
  const host = draw(['core.keep-awake'], false);
  const tile = host.querySelector<HTMLElement>('button.dz-glance--icon')!;
  expect(press(tile, { key: 'F10', shiftKey: true }).defaultPrevented).toBe(false);
  expect(openMenu()).toBeNull();
});
