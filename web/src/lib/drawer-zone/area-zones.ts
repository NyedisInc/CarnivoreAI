import { resolvePlacement, type ResolvedPlacement } from '../../opscenter/widgets/placement-resolve';
import type { WidgetManifest } from '../../opscenter/widgets/types';
import type { PlacementOptions } from '../../opscenter/widgets/placement-options';
import { createZone, type Zone } from '../zone-shell/zone.svelte';
import { HOST_LOOKS } from '../zone-shell/host-looks';
import type { PanelState, TabRef, ZoneMenuAnchor } from '../zone-shell/zone-types';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { widgetArea } from '../dynamic-tabs/widget-area.svelte';
import type { WidgetAreaState } from '../dynamic-tabs/types';
import { drawerZone } from './zone-store.svelte';
import { zoneItemKey, type ZoneItem } from './zone-model';

export const GLANCE_ZONE_KEY = 'drawer:glance';

const AREA_PANEL: Readonly<Record<WidgetAreaState, PanelState>> = { full: 'open', glance: 'collapsed', closed: 'closed' };

export function areaPanel(state: WidgetAreaState): PanelState {
  return AREA_PANEL[state];
}

export function areaState(): WidgetAreaState {
  return widgetArea.stateFor(sidebarTabs.active());
}

export function cardZoneKey(itemKey: string): string {
  return `drawer:${itemKey}`;
}

export interface DrawnCard {
  item: ZoneItem;
  key: string;
  manifest: WidgetManifest;
  tab: TabRef;
}

export function drawnCards(): DrawnCard[] {
  return drawerZone.items.flatMap((item) => {
    const placement = resolvePlacement({ widget: item.widget, view: item.view, target: item.target ?? null, instance: item.instance ?? null });
    if (!placement) return [];
    const key = zoneItemKey(item);
    return [{ item, key, manifest: placement.manifest, tab: { key, kind: 'widget', placement, options: item.options } }];
  });
}

export function cardHeaderId(placement: ResolvedPlacement): string {
  return HOST_LOOKS.drawer.keyFor(placement.cell, placement.target, placement.instance);
}

const cards = new Map<string, Zone>();

export function drawerCardZone(itemKey: string): Zone {
  let zone = cards.get(itemKey);
  if (!zone) {
    zone = createZone({
      key: cardZoneKey(itemKey),
      tabs: () => drawnCards().flatMap((card) => (card.key === itemKey ? [card.tab] : [])),
      active: () => itemKey,
      select: () => {},
      panel: () => areaPanel(areaState()),
      strip: 'none',
      toolbar: 'header',
      menuHost: 'drawer-card',
      headerId: (tab) => (tab.placement ? cardHeaderId(tab.placement) : `${cardZoneKey(itemKey)}#${tab.key}`),
    });
    cards.set(itemKey, zone);
  }
  return zone;
}

export function drawerCardZones(): Zone[] {
  const keys = drawnCards().map((card) => card.key);
  for (const key of cards.keys()) if (!keys.includes(key)) cards.delete(key);
  return keys.map(drawerCardZone);
}

export interface GlanceEntry {
  key: string;
  widget: string;
  manifest: WidgetManifest;
  options?: PlacementOptions;
}

export function glanceEntries(): GlanceEntry[] {
  return drawerZone.glance.flatMap((placement) => {
    const resolved = resolvePlacement({ widget: placement.widget });
    return resolved ? [{ key: placement.id, widget: placement.widget, manifest: resolved.manifest, options: placement.options }] : [];
  });
}

export function createGlanceZone(entries: () => readonly GlanceEntry[], show: (entry: GlanceEntry, anchor: ZoneMenuAnchor) => void): Zone {
  return createZone({
    key: GLANCE_ZONE_KEY,
    tabs: () => entries().map((entry) => ({ key: entry.key, kind: 'widget', options: entry.options })),
    active: () => null,
    select: () => {},
    panel: () => 'collapsed',
    strip: 'keys',
    toolbar: 'none',
    menuHost: 'glance',
    openMenu: (tab, anchor) => {
      const entry = entries().find((one) => one.key === tab.key);
      if (!entry) return false;
      show(entry, anchor);
      return true;
    },
  });
}
