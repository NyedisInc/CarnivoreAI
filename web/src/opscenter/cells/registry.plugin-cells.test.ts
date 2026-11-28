/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount, type Component } from 'svelte';
import { PLUGIN_CELL_IDS, REGISTRY, entryFor, registerPluginCell } from './registry';
import { META } from '../engine/meta';
import { t } from '../../lib/i18n/index.svelte';

let mounted: ReturnType<typeof mount> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; localStorage.clear(); vi.unstubAllGlobals(); });

const Stub: Component<Record<string, unknown>> = (internals) => {
  if (internals instanceof CharacterData) {
    const el = document.createElement('i');
    el.dataset.stubCell = '';
    internals.before(el);
  }
  return {};
};

test('the registry holds no component for a plugin cell id, and every one still has its record in the meta', () => {
  for (const id of PLUGIN_CELL_IDS) {
    expect(id in REGISTRY).toBe(false);
    expect(META[id]).toBeDefined();
  }
});

test('a slot of a plugin cell id draws the unavailable line before any registration, then the component once it registers', async () => {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  const { createLayoutStore } = await import('../engine/layout.svelte');
  const { default: CellHost } = await import('../CellHost.svelte');
  const store = createLayoutStore('home');
  for (const id of PLUGIN_CELL_IDS) expect(entryFor(id)).toBeUndefined();
  const host = document.body.appendChild(document.createElement('div'));
  mounted = mount(CellHost, { target: host, props: { id: 'task-manager-mk2', store } });
  await tick();
  expect(host.querySelector('.oc-cell-unavailable')?.textContent).toBe(t('opscenter.cell.unavailable'));

  registerPluginCell('task-manager-mk2', Stub);
  flushSync(); await tick(); await tick();
  expect(entryFor('task-manager-mk2')?.component).toBe(Stub);
  expect(host.querySelector('.oc-cell-unavailable')).toBeNull();
  expect(host.querySelector('[data-stub-cell]')).not.toBeNull();
  expect(entryFor('task-manager-mk2-all')).toBeUndefined();
});
