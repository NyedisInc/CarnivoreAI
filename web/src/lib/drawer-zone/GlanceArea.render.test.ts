/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({ status: 'ok' as const, data: null as LedgerSnapshot | null, fetchedAt: null as number | null, error: null as string | null }));
vi.mock('../../opscenter/api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), ledger: fakeLedger, primarySessionId: () => '' }));

import DrawerZone from './DrawerZone.svelte';
import { drawerZone } from './zone-store.svelte';
import { ZONE_FIELD } from './zone-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { widgetArea } from '../dynamic-tabs/widget-area.svelte';

const acct = (id: string, provider: string) => ({
  id, name: `${id} name`, short_name: id, provider, plan: 'max', identity: id, credential_state: 'ok', fetched_at: null, next_poll_at: null, error: null, color: null, managed: false, windows: [],
});
const LEDGER = { accounts: [acct('joe', 'claude'), acct('work', 'claude')], total: { accounts: 2, windows: [] }, loop: { alive: true, last_pass_at: null } } as unknown as LedgerSnapshot;

let host: HTMLElement;
let instance: unknown = null;
let written: Record<string, unknown>[] = [];

const area = (): HTMLElement | null => host.querySelector<HTMLElement>('[data-glance-area]');
const places = (): HTMLElement[] => [...host.querySelectorAll<HTMLElement>('[data-glance-place]')];
const edit = (on: boolean): void => {
  layoutEditor.active = on;
  flushSync();
};
const setArea = (state: 'full' | 'glance'): void => {
  widgetArea.set(sidebarTabs.active(), state);
  flushSync();
};

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  // the settings overlay
  (HTMLElement.prototype as unknown as { showPopover: () => void }).showPopover = function (): void {};
  fakeLedger.data = LEDGER;
  written = [];
  drawerZone.stored = [{ widget: 'core.ledger', look: null }];
  drawerZone.glanceStored = [];
  layoutEditor.active = false;
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: () => ({ v: 1, items: [{ widget: 'core.ledger' }], glance: [] }),
    write: async (field: string, value: Record<string, unknown>) => {
      expect(field).toBe(ZONE_FIELD);
      written.push(value);
      return { status: 'committed' };
    },
    follow: () => () => {},
  };
  host = document.createElement('div');
  host.id = 'session-sidebar-ledger';
  document.body.appendChild(host);
  instance = mount(DrawerZone, { target: host });
  setArea('full');
});

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host.remove();
  layoutEditor.active = false;
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

describe('the glance area', () => {
  test('takes the providers widget twice, each placement showing the account its own option names', () => {
    edit(true);
    expect(drawerZone.addGlance('core.ledger', true)).not.toBeNull();
    expect(drawerZone.addGlance('core.ledger', true)).not.toBeNull();
    expect(drawerZone.addGlance('core.keep-awake', false)).not.toBeNull();
    expect(drawerZone.addGlance('core.keep-awake', false)).toBeNull();
    flushSync();
    expect(places().map((p) => p.dataset['glanceWidget'])).toEqual(['core.ledger', 'core.ledger', 'core.keep-awake']);
    expect(places().map((p) => !!p.querySelector('[data-glance-options]'))).toEqual([true, true, false]);

    const choose = (index: number, account: string): void => {
      places()[index]!.querySelector<HTMLButtonElement>('[data-glance-options]')!.click();
      flushSync();
      const overlay = document.querySelector<HTMLElement>('[data-settings-overlay="core.ledger"]')!;
      const select = overlay.querySelector<HTMLSelectElement>('select')!;
      expect([...select.options].map((o) => o.textContent)).toEqual(['every account', 'joe', 'work']);
      select.value = account;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      flushSync();
      overlay.querySelector<HTMLButtonElement>('[data-configure-done]')!.click();
      flushSync();
    };
    choose(0, 'joe');
    choose(1, 'work');

    const last = written.at(-1) as { glance: { id: string; widget: string; options?: Record<string, string> }[] };
    expect(last.glance.map((p) => [p.widget, p.options?.['account'] ?? null])).toEqual([
      ['core.ledger', 'joe'],
      ['core.ledger', 'work'],
      ['core.keep-awake', null],
    ]);
    expect(new Set(last.glance.map((p) => p.id)).size).toBe(3);

    edit(false);
    setArea('glance');
    const tiles = [...host.querySelectorAll<HTMLElement>('[data-glance-tile]')];
    expect(tiles.map((tile) => tile.dataset['glanceTile'])).toEqual(['joe', 'work']);
    expect(new Set(tiles.map((tile) => tile.dataset['glancePlacement'])).size).toBe(2);
  });

  test('appears under the open area only in edit mode, in yellow dashes painted in front, with no words', () => {
    expect(area()).toBeNull();
    edit(true);
    const shown = area()!;
    expect(shown).not.toBeNull();
    const widget = host.querySelector('[data-zone-item="core.ledger"]')!;
    expect(widget.compareDocumentPosition(shown) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(shown.textContent!.trim()).toBe('');
    edit(false);
    expect(area()).toBeNull();

    const source = readFileSync(join(__dirname, 'GlanceArea.svelte'), 'utf8');
    const rule = source.slice(source.indexOf('.dz-garea::after {'), source.indexOf('}', source.indexOf('.dz-garea::after {')));
    expect(rule).toMatch(/border:\s*var\(--oc-border\)\s+dashed\s+var\(--oc-yellow\)/);
    expect(rule).toMatch(/z-index:\s*60/);
    expect(rule).toMatch(/pointer-events:\s*none/);
  });
});
