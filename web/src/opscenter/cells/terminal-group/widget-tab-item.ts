import { t } from '../../../lib/i18n/index.svelte';
import { isWidgetDisabled } from '../../../lib/item-settings/store.svelte';
import { categoryKey } from '../../layout-editor/drawer-model';
import { allManifests, manifestById } from '../../widgets/core-manifests';
import { isGlobalWidget } from '../../widgets/global-scope';
import { resolvePlacement } from '../../widgets/placement-resolve';
import { isViewCell, mergedIds } from '../../widgets/views';
import { HOST_LOOKS } from '../../../lib/zone-shell/host-looks';
import type { WidgetManifest } from '../../widgets/types';
import { widgetIdOfTab, widgetTabId, widgetTargetOfTab } from '../../engine/widget-tabs';
import { kindOf } from '../../engine/meta';
import type { SlotId } from '../../engine/types';
import { panels } from '../../engine/plugin-kinds';
import type { TabItem } from '../../shell/TabStrip.svelte';
import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';

export const WIDGET_TAB_FAMILY = 'browser';

const MISSING_GLYPH = 'close';

const PLUGIN_GONE_GLYPH = 'plug';

export function widgetTabManifest(widgetId: string): WidgetManifest | null {
  const manifest = manifestById(widgetId);
  return manifest && !isWidgetDisabled(manifest.id) ? manifest : null;
}

export function widgetTabItem(tab: string, widgetId: string): TabItem {
  const manifest = widgetTabManifest(widgetId);
  if (!manifest && widgetTargetOfTab(tab) !== null) {
    if (!panels().loaded()) return { id: tab, name: t('opscenter.tabs.plugin_loading_name'), family: WIDGET_TAB_FAMILY, glyph: PLUGIN_GONE_GLYPH };
    return { id: tab, name: t('opscenter.tabs.plugin_gone_name'), family: WIDGET_TAB_FAMILY, glyph: PLUGIN_GONE_GLYPH };
  }
  if (!manifest) return { id: tab, name: t('opscenter.tabs.widget_gone_name'), family: WIDGET_TAB_FAMILY, glyph: MISSING_GLYPH };
  return {
    id: tab,
    name: t(manifest.titleKey),
    family: WIDGET_TAB_FAMILY,
    glyph: manifest.icon,
    badge: { global: isGlobalWidget(manifest.id) },
  };
}

export function widgetMenuNodes(
  here: ReadonlySet<string>,
  open: (widgetId: string, target?: string) => void,
  gridSlots: ReadonlySet<SlotId> = new Set(),
): MenuNode[] {
  const byCategory = new Map<string, MenuNode[]>();
  for (const manifest of Object.values(panels().manifests())) {
    const tail = panels().tail(manifest.id);
    if (!tail) continue;
    const key = widgetTabId(manifest.id, tail);
    if (widgetIdOfTab(key) !== manifest.id || widgetTargetOfTab(key) !== tail) continue;
    if (here.has(key) || [...gridSlots].some((slot) => kindOf(slot) === manifest.id)) continue;
    const leaves = byCategory.get(manifest.category) ?? [];
    leaves.push({ id: `widget/${manifest.id}`, label: t(manifest.titleKey), icon: manifest.icon, keyless: true, run: () => open(manifest.id, tail) });
    byCategory.set(manifest.category, leaves);
  }
  for (const manifest of Object.values(allManifests())) {
    if (manifest.instancing !== 'singleton' || isViewCell(manifest) || isWidgetDisabled(manifest.id)) continue;
    if (!manifest.canvases.includes('terminal') || here.has(widgetTabId(manifest.id))) continue;
    const leaves = byCategory.get(manifest.category) ?? [];
    leaves.push({ id: `widget/${manifest.id}`, label: t(manifest.titleKey), icon: manifest.icon, run: () => open(manifest.id) });
    byCategory.set(manifest.category, leaves);
  }
  return [...byCategory.entries()].map(([category, leaves]) => ({
    id: `widget/${category}`,
    label: t(categoryKey(category as WidgetManifest['category'])),
    children: leaves.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' })),
  }));
}

export interface WidgetTabBinding {
  widget: WidgetManifest;
  view: string | null;
  cell: WidgetManifest;
  target: string | null;
}

export function widgetTabBinding(widgetId: string, target: string | null = null): WidgetTabBinding | null {
  if (target) void panels().revision();
  const manifest = widgetTabManifest(widgetId);
  if (!manifest) return null;
  const tail = target && panels().isPanel(widgetId) ? target : null;
  const merged = mergedIds(allManifests())[manifest.id];
  const stored = merged ? manifestById(merged.widget) : undefined;
  const widget = stored ?? manifest;
  const view = stored ? merged!.view : null;
  const resolved = resolvePlacement({ widget, view, target: tail });
  return resolved ? { widget, view, cell: resolved.cell, target: tail } : null;
}

export function widgetTabBodyKey(widgetId: string, target: string | null = null): string | null {
  const binding = widgetTabBinding(widgetId, target);
  return binding ? HOST_LOOKS.tab.keyFor(binding.cell, target, null) : null;
}
