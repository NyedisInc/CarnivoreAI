/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { panels, setPanelProvider, type PanelProvider } from '../../engine/plugin-kinds';
import { manifestById } from '../../widgets/core-manifests';
import { widgetIdOfTab, widgetTabId, widgetTargetOfTab } from '../../engine/widget-tabs';
import { panelEntries } from '../../../lib/cplug-ui/panel-views.svelte';
import type { CplugRow } from '../../../lib/plugins-page/cplugs-adapter';
import { widgetMenuNodes, widgetTabBinding, widgetTabItem } from './widget-tab-item';

const original = panels();
afterEach(() => setPanelProvider(original));

function provide(kinds: string[], over: Partial<PanelProvider> = {}): void {
  const base = manifestById('core.notes')!;
  const manifests = Object.fromEntries(kinds.map((kind) => [kind, { ...base, id: kind, instancing: 'per-target', category: 'plugins' }]));
  setPanelProvider({ ...original, manifests: () => manifests as never, isPanel: (kind) => kinds.includes(kind), tail: () => 'panel-ab12cd34', ...over });
}

const row = (id: string, view: string): CplugRow =>
  ({ id, runtime: 'sidecar', enabled: true, state: 'active', views: [{ name: view, surfaces: ['panel'] }] }) as unknown as CplugRow;

test('a 24 character plugin id with a 40 character view makes no panel kind (it would not fit a tab key)', () => {
  const id = 'a'.repeat(24);
  expect(panelEntries([row(id, 'b'.repeat(40))])).toEqual([]);
  expect(panelEntries([row(id, 'b'.repeat(39))]).map((entry) => entry.kind)).toEqual([`${id}.${'b'.repeat(39)}`]);
});

test('the + menu leaves out a view whose tab key does not read back', () => {
  const long = `${'a'.repeat(24)}.${'b'.repeat(40)}`;
  provide([long, 'hello.game']);
  const leaves = widgetMenuNodes(new Set(), () => {}).flatMap((node) => node.children ?? []).map((leaf) => leaf.id);
  expect(leaves).toContain('widget/hello.game');
  expect(leaves).not.toContain(`widget/${long}`);
});

test('until the plugin list answers a view tab holds a neutral sentence, never plugin off', () => {
  provide([], { loaded: () => false });
  const tab = widgetTabId('hello.game', 'panel-ab12cd34');
  expect(widgetTabItem(tab, 'hello.game').name).not.toBe('plugin off');
  provide([], { loaded: () => true });
  expect(widgetTabItem(tab, 'hello.game').name).toBe('plugin off');
});

test('a tail on a core widget tab is ignored by the binding', () => {
  expect(widgetIdOfTab('widget:core.tasks@panel-ab12cd34')).toBe('core.tasks');
  expect(widgetTargetOfTab('widget:core.tasks@panel-ab12cd34')).toBe('panel-ab12cd34');
  expect(widgetTabBinding('core.tasks', 'panel-ab12cd34')?.target).toBeNull();
});
