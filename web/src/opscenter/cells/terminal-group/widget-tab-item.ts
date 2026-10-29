import { t } from '../../../lib/i18n/index.svelte';
import { isWidgetDisabled } from '../../../lib/item-settings/store.svelte';
import { categoryKey } from '../../layout-editor/drawer-model';
import { allManifests, manifestById } from '../../widgets/core-manifests';
import { isGlobalWidget } from '../../widgets/global-scope';
import { resolvePlacement } from '../../widgets/placement-resolve';
import { isViewCell, mergedIds } from '../../widgets/views';
import { HOST_LOOKS } from '../../../lib/zone-shell/host-looks';
import type { WidgetManifest } from '../../widgets/types';
import { widgetTabId } from '../../engine/widget-tabs';
import type { TabItem } from '../../shell/TabStrip.svelte';
import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';

export const WIDGET_TAB_FAMILY = 'browser';

const MISSING_GLYPH = 'close';

export function widgetTabManifest(widgetId: string): WidgetManifest | null {
  const manifest = manifestById(widgetId);
  return manifest && !isWidgetDisabled(manifest.id) ? manifest : null;
}

export function widgetTabItem(tab: string, widgetId: string): TabItem {
  const manifest = widgetTabManifest(widgetId);
  if (!manifest) return { id: tab, name: t('opscenter.tabs.widget_gone_name'), family: WIDGET_TAB_FAMILY, glyph: MISSING_GLYPH };
  return {
    id: tab,
    name: t(manifest.titleKey),
    family: WIDGET_TAB_FAMILY,
    glyph: manifest.icon,
    badge: { manifest, global: isGlobalWidget(manifest.id) },
  };
}

export function widgetMenuNodes(here: ReadonlySet<string>, open: (widgetId: string) => void): MenuNode[] {
  const byCategory = new Map<string, MenuNode[]>();
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
}

export function widgetTabBinding(widgetId: string): WidgetTabBinding | null {
  const manifest = widgetTabManifest(widgetId);
  if (!manifest) return null;
  const merged = mergedIds(allManifests())[manifest.id];
  const stored = merged ? manifestById(merged.widget) : undefined;
  const widget = stored ?? manifest;
  const view = stored ? merged!.view : null;
  const resolved = resolvePlacement({ widget, view });
  return resolved ? { widget, view, cell: resolved.cell } : null;
}

export function widgetTabBodyKey(widgetId: string): string | null {
  const binding = widgetTabBinding(widgetId);
  return binding ? HOST_LOOKS.tab.keyFor(binding.cell, null, null) : null;
}
