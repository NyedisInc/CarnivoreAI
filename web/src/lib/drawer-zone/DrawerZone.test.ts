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
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { ZONE_FIELD } from './zone-model';

const ONE: LedgerSnapshot = {
  accounts: [
    {
      id: 'main',
      name: 'main',
      short_name: null,
      provider: 'claude',
      plan: 'max 20x',
      identity: 'acme',
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
  layoutEditor.active = false;
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
  layoutEditor.active = false;
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

const items = (): string[] => [...host!.querySelectorAll<HTMLElement>('[data-zone-item]')].map((e) => e.dataset['zoneItem']!);
const edit = (on: boolean): void => {
  layoutEditor.active = on;
  flushSync();
};

describe('outside edit layout', () => {
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

describe('in edit layout', () => {
  test('the cyan box wraps the widgets only: the glance area sits under it, and no sizer is drawn', () => {
    edit(true);
    const widgets = host!.querySelector('[data-zone-widgets]')!;
    expect(widgets.classList.contains('dz-widgets--editing')).toBe(true);
    const glance = host!.querySelector('[data-glance-area]');
    expect(glance).not.toBeNull();
    expect(widgets.contains(glance)).toBe(false);
    expect(host!.querySelector('[data-zone-grip], .dz-grip, [role="separator"]')).toBeNull();
  });

  test('each item shows its strip; reorder, look and remove work and save', () => {
    drawerZone.add('core.keep-awake');
    edit(true);
    expect(host!.querySelectorAll('.dz-strip')).toHaveLength(2);

    host!.querySelectorAll<HTMLElement>('[data-zone-down]')[0]!.click();
    flushSync();
    expect(items()).toEqual(['core.keep-awake', 'core.ledger']);

    host!.querySelector<HTMLElement>('[data-zone-look="full"]')!.click();
    flushSync();
    const ledgerItem = host!.querySelector('[data-zone-item="core.ledger"]')!;
    expect(ledgerItem.getAttribute('data-look')).toBe('full');
    expect(ledgerItem.querySelector('[data-zone-cell="core.ledger"]')).not.toBeNull();

    host!.querySelector<HTMLElement>('[data-zone-item="core.keep-awake"] [data-zone-remove]')!.click();
    flushSync();
    expect(items()).toEqual(['core.ledger']);
    expect(written.at(-1)).toEqual({ v: 1, items: [{ widget: 'core.ledger', look: 'full' }] });
  });

  test('only a widget with more than one look shows the look picker', () => {
    drawerZone.add('core.keep-awake');
    edit(true);
    expect(host!.querySelector('[data-zone-item="core.ledger"] [data-zone-look]')).not.toBeNull();
    expect(host!.querySelector('[data-zone-item="core.keep-awake"] [data-zone-look]')).toBeNull();
  });

  test('an emptied area shows the drop hint, and leaving edit layout hides it', () => {
    drawerZone.remove('core.ledger');
    edit(true);
    expect(host!.querySelector('[data-zone-empty]')).not.toBeNull();
    edit(false);
    expect(host!.querySelector('[data-zone-empty]')).toBeNull();
  });
});
