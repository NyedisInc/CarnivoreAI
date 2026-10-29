import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { railHostsTab } from '../sidebar-widgets/flyout.svelte';
import { DEFAULT_DRAWER_TAB } from '../drawer-tabs/drawer-tabs';
import { createZone, type Zone } from '../zone-shell/zone.svelte';
import type { TabRef } from '../zone-shell/zone-types';

export const ROOT_ZONE_KEY = 'drawer:root';

export const SESSION_LIST_TAB = DEFAULT_DRAWER_TAB;

export function rootZoneTabs(): readonly TabRef[] {
  return sidebarTabs
    .present()
    .filter((def) => def.id === SESSION_LIST_TAB || ('component' in def.body && !railHostsTab(def.id)))
    .map((def) => ({ key: def.id, kind: 'panel' }));
}

let zone: Zone | null = null;

export function rootZone(): Zone {
  zone ??= createZone({
    key: ROOT_ZONE_KEY,
    tabs: rootZoneTabs,
    active: () => sidebarTabs.active(),
    select: (key) => void sidebarTabs.select(key),
    panel: () => 'open',
    strip: 'none',
    toolbar: 'header',
    menuHost: 'drawer-card',
  });
  return zone;
}
