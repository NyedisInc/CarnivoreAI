/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import type { LedgerSnapshot } from '../../api/types';

const fakeLedger = vi.hoisted(() => ({ status: 'ok' as const, data: null as LedgerSnapshot | null, fetchedAt: null as number | null, error: null as string | null }));
vi.mock('../../api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), ledger: fakeLedger }));

import FrameFitBody from './FrameFitBody.svelte';
import { closeConfigure, configureSheet, openConfigure } from './configure.svelte';
import { declareSettingsPanel } from './settings-panels.svelte';
import { homeLayout } from '../../engine/layout.svelte';
import { META, metaFor } from '../../engine/meta';
import { layoutEditor } from '../../layout-editor/editor.svelte';
import { CORE_MANIFESTS } from '../core-manifests';
import PlacementBody from '../../../lib/zone-shell/PlacementBody.svelte';
import GlanceRow from '../../../lib/drawer-zone/GlanceRow.svelte';
import '../../../lib/drawer-zone/glances';
import { drawerZone } from '../../../lib/drawer-zone/zone-store.svelte';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';
import type { SlotId } from '../../engine/types';

installPopoverPolyfill();

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  layoutEditor.active = false;
  layoutEditor.page = null;
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  closeConfigure();
  document.body.replaceChildren();
});

function place(component: unknown, props: Record<string, unknown>): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(component as never, { target, props }));
  flushSync();
  return target;
}

test('an analytics chart on the grid: config opens its own panel with edit layout OFF, and it stays open', () => {
  const slot = 'analytics:11111111-1111-4111-8111-111111111111' as SlotId;
  const panel = createRawSnippet(() => ({ render: () => '<div data-test-panel>chart settings</div>' }));
  const withdraw = declareSettingsPanel(slot, panel);
  const frame = document.createElement('section');
  document.body.append(frame);
  const body = createRawSnippet(() => ({ render: () => '<div>chart</div>' }));
  place(FrameFitBody, { meta: metaFor(slot, META), store: homeLayout, frame, titleRowPx: 32, body });
  openConfigure(slot);
  flushSync();
  flushSync();
  expect(layoutEditor.active).toBe(false);
  expect(configureSheet.slot, 'the frame no longer closes it outside edit layout').toBe(slot);
  expect(document.querySelector('[data-test-panel]')).not.toBeNull();
  withdraw();
  flushSync();
  expect(configureSheet.slot).toBeNull();
});

test('a widget in the sidebar widget area: settings... is an item of its icon menu in edit layout; the hover gear and the header gear are gone', () => {
  layoutEditor.active = true;
  layoutEditor.page = 'home';
  const root = place(PlacementBody, { host: 'drawer', manifest: CORE_MANIFESTS['core.activity-log']! });
  expect(root.querySelector('[data-zone-settings]'), 'no gear key in the header').toBeNull();
  root.querySelector<HTMLButtonElement>('[data-corner]')!.click();
  flushSync();
  document.querySelector<HTMLElement>('[data-node="settings"]')!.click();
  flushSync();
  expect(document.querySelector('[data-settings-overlay="core.activity-log"]')).not.toBeNull();
  closeConfigure();
  layoutEditor.active = false;
  document.body.replaceChildren();
  const plain = place(PlacementBody, { host: 'drawer', manifest: CORE_MANIFESTS['core.activity-log']! });
  plain.querySelector<HTMLButtonElement>('[data-corner]')!.click();
  flushSync();
  expect(document.querySelector('[data-node="settings"]')).toBeNull();
  expect(document.querySelector('[data-node="close-widget"]')).not.toBeNull();
});

test('a glance placement: no hover gear; a right-click opens its menu, and settings... opens the options outside edit layout', () => {
  const id = drawerZone.addGlance('core.ledger', true)!;
  expect(id).toBeTruthy();
  const root = place(GlanceRow, {
    entries: [{ key: id, widget: 'core.ledger', manifest: CORE_MANIFESTS['core.ledger']!, options: {} }],
    onopen: () => {},
    options: true,
  });
  expect(root.querySelector('[data-glance-row-options]'), 'the invisible hover gear is gone').toBeNull();
  root.querySelector<HTMLElement>(`[data-glance-row-place="${id}"]`)!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
  document.querySelector<HTMLElement>('[data-node="settings"]')!.click();
  flushSync();
  expect(document.querySelector('[data-settings-overlay="core.ledger"]')).not.toBeNull();
  drawerZone.removeGlance(id);
  const bare = place(GlanceRow, { entries: [{ key: 'x', widget: 'core.ledger', manifest: CORE_MANIFESTS['core.ledger']! }], onopen: () => {} });
  expect(bare.querySelector('[data-glance-row-place]')).toBeNull();
});
