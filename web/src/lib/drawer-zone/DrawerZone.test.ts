/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import type { LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({
  status: 'ok' as 'loading' | 'ok',
  data: null as LedgerSnapshot | null,
  fetchedAt: null as number | null,
  error: null as string | null,
}));

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, ledger: fakeLedger, primarySessionId: () => '' };
});

import DrawerZone from './DrawerZone.svelte';
import { drawerZone } from './zone-store.svelte';
import { dropHostById } from '../motion-grid';
import { ZONE_FIELD } from './zone-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';

const ONE: LedgerSnapshot = {
  accounts: [
    {
      id: 'main',
      name: 'main',
      short_name: null,
      provider: 'claude',
      plan: 'max 20x',
      identity: 'alex',
      credential_state: 'ok',
      fetched_at: null,
      next_poll_at: null,
      error: null,
      windows: [],
      color: null,
      managed: false,
    },
  ],
  total: { accounts: 1, windows: [] },
  loop: { alive: true, last_pass_at: null },
};

let host: HTMLElement | null = null;
let instance: unknown = null;
let written: unknown[] = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  fakeLedger.data = ONE;
  written = [];
  drawerZone.stored = null;
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: () => null,
    write: async (field: string, value: unknown) => {
      expect(field).toBe(ZONE_FIELD);
      written.push(value);
      return { status: 'committed' };
    },
    follow: () => () => {},
  };
  const zoneHost = document.createElement('div');
  zoneHost.id = 'session-sidebar-ledger';
  document.body.appendChild(zoneHost);
  host = zoneHost;
  instance = mount(DrawerZone, { target: zoneHost });
  flushSync();
});

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host?.remove();
  host = null;
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

const items = (): string[] => [...host!.querySelectorAll<HTMLElement>('[data-zone-item]')].map((e) => e.dataset['zoneItem']!);

describe('the area', () => {
  test('defaults to the providers panel in its compact look, with no edit strip', () => {
    expect(items()).toEqual(['core.ledger']);
    expect(host!.querySelector('.ldp')).not.toBeNull();
    expect(host!.querySelector('[data-zone-item]')!.getAttribute('data-look')).toBe('compact');
    expect(host!.querySelector('.dz-strip')).toBeNull();
    expect(written).toEqual([]);
  });

  test('another widget stacks under it and draws its own body', () => {
    drawerZone.add('core.keep-awake');
    flushSync();
    expect(items()).toEqual(['core.ledger', 'core.keep-awake']);
    expect(host!.querySelector('[data-zone-cell="core.keep-awake"]')).not.toBeNull();
  });

  test('an id this build does not carry is kept in the list and simply not drawn', () => {
    drawerZone.stored = [
      { widget: 'core.ledger', look: null },
      { widget: 'acme.clock', look: null },
    ];
    flushSync();
    expect(items()).toEqual(['core.ledger']);
    expect(drawerZone.items.map((i) => i.widget)).toContain('acme.clock');
  });
});

describe('an emptied area', () => {
  test('keeps the nodes the core appended to the column (its landing box and live region) when the last card leaves', () => {
    const column = host!.querySelector<HTMLElement>('[data-zone-widgets]')!;
    const core = document.createElement('div');
    core.dataset['coreOwned'] = '';
    column.appendChild(core);
    drawerZone.stored = [];
    flushSync();
    expect(items()).toEqual([]);
    expect(column.contains(core)).toBe(true);
  });
});

describe('always on (no edit mode)', () => {
  test('every card sits in a motion wrapper and no edit strip is drawn', () => {
    drawerZone.add('core.keep-awake');
    flushSync();
    const cells = [...host!.querySelectorAll<HTMLElement>('[data-zone-widgets] > .dz-cells > .dz-cell')];
    expect(cells.map((c) => c.getAttribute('data-stack-id'))).toEqual(['core.ledger', 'core.keep-awake']);
    expect(cells.every((c) => c.classList.contains('motion-item'))).toBe(true);
    expect(host!.querySelector('.dz-strip')).toBeNull();
  });

  test('the zone header (only the +, no words) is drawn only while layout editing is on', () => {
    expect(host!.querySelector('[data-zone-head]')).toBeNull();
    layoutEditor.active = true;
    flushSync();
    const head = host!.querySelector<HTMLElement>('[data-zone-head]');
    expect(head).not.toBeNull();
    expect(head!.textContent!.trim()).toBe('');
    layoutEditor.active = false;
    flushSync();
    expect(host!.querySelector('[data-zone-head]')).toBeNull();
  });

  test('the + in the zone header asks the widget drawer to open on this zone', () => {
    layoutEditor.active = true;
    flushSync();
    const seen: unknown[] = [];
    const on = (e: Event): void => void seen.push((e as CustomEvent).detail);
    document.addEventListener('oc-widget-drawer-open', on);
    host!.querySelector<HTMLElement>('[data-zone-add]')!.click();
    document.removeEventListener('oc-widget-drawer-open', on);
    layoutEditor.active = false;
    expect(seen).toEqual([{ surface: 'zone:drawer' }]);
  });

  test('the zone is a drop host: it takes a widget it does not hold, refuses a held singleton, and add() appends and saves', () => {
    const zoneHost = dropHostById('zone:drawer')!;
    expect(zoneHost).not.toBeNull();
    expect(zoneHost.takes!('core.keep-awake')).toBe(true);
    expect(zoneHost.takes!('core.ledger')).toBe(false);
    expect(zoneHost.add!('core.keep-awake')).toBe(true);
    flushSync();
    expect(items()).toEqual(['core.ledger', 'core.keep-awake']);
    expect(written.at(-1)).toEqual({ v: 1, items: [{ widget: 'core.ledger' }, { widget: 'core.keep-awake' }] });
  });

  test('an emptied area shows the drop hint', () => {
    drawerZone.remove('core.ledger');
    flushSync();
    expect(host!.querySelector('[data-zone-empty]')).not.toBeNull();
  });
});
