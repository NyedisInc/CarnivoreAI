import { tabRegistry, type TabRegistry } from '../dynamic-tabs/registry';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import type { DynamicTabDef } from '../dynamic-tabs/types';
import { sidebarWidgets, type SidebarWidgetRegistry } from './registry';
import type { SidebarWidget } from './types';

export const TAB_FLYOUT_PREFIX = 'tab.';

export function tabFlyoutId(tab: string): string {
  return `${TAB_FLYOUT_PREFIX}${tab}`;
}

function claimedElsewhere(tab: string, registry: SidebarWidgetRegistry): boolean {
  return registry.all().some((w) => !w.id.startsWith(TAB_FLYOUT_PREFIX) && w.tab === tab);
}

export function tabFlyoutWidget(def: DynamicTabDef, registry: SidebarWidgetRegistry = sidebarWidgets): SidebarWidget {
  const bodyTitle = 'component' in def.body ? def.body.titleKey : undefined;
  return {
    id: tabFlyoutId(def.id),
    titleKey: def.nameKey ?? bodyTitle ?? def.labelKey,
    icon: def.icon,
    kind: 'registered',
    surface: 'flyout',
    tint: '--oc-cyan',
    order: def.order,
    present: () => sidebarTabs.isPresent(def) && !claimedElsewhere(def.id, registry),
    badge: def.badge ? () => def.badge?.() ?? null : undefined,
    tab: def.railAction ? undefined : def.id,
    opensFromTab: def.railAction ? undefined : true,
    action: def.railAction,
    close: def.close ? () => sidebarTabs.close(def.id) : undefined,
    parts: { body: { tab: def.id } },
  };
}

export function registerTabFlyouts(registry: SidebarWidgetRegistry = sidebarWidgets, tabs: TabRegistry = tabRegistry): void {
  for (const def of tabs.all()) {
    if (!('component' in def.body) || registry.has(tabFlyoutId(def.id))) continue;
    registry.register(tabFlyoutWidget(def, registry));
  }
}
