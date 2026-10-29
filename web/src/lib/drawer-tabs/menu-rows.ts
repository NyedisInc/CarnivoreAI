import { RAIL_DESTINATIONS, RAIL_HELP_LINKS, WARROOM_ROW, railItemVisible, type RailItem } from '../../opscenter/shell/rail-items';
import { activeFlyout, pressRail } from '../sidebar-widgets/flyout.svelte';
import { railEntries } from '../sidebar-widgets/rail-model';
import { MENU_FLYOUT, SESSION_LIST_WIDGET, SWARM_FLYOUT } from '../sidebar-widgets/widget-ids';
import { orderedMenuItems, storedMenuOrder } from './menu-order.svelte';
import { resolveRailZones } from '../sidebar-widgets/rail-zones';

export function menuLeadItems(): RailItem[] {
  const { fixed, registered } = railEntries();
  const swarmFirst = [...registered].sort((a, b) => Number(b.id === SWARM_FLYOUT) - Number(a.id === SWARM_FLYOUT));
  return orderedMenuItems([...fixed.filter((w) => w.id !== MENU_FLYOUT), ...swarmFirst].map((w) => ({
    id: w.id,
    icon: w.icon,
    labelKey: w.titleKey,
    hint: '',
    widgetId: w.id,
    badge: w.badge,
    close: w.close,
    pressed: w.action ? undefined : () => (w.id === SESSION_LIST_WIDGET ? activeFlyout() === null : activeFlyout() === w.id),
    run: () => void pressRail(w.id),
  })));
}

export function menuHelpLinks(): RailItem[] {
  return orderedMenuItems(RAIL_HELP_LINKS);
}

export function menuDestinations(): RailItem[] {
  return orderedMenuItems(RAIL_DESTINATIONS.filter((i) => i.id !== 'settings').filter(railItemVisible));
}

export function menuSettings(): RailItem | undefined {
  return RAIL_DESTINATIONS.find((i) => i.id === 'settings');
}

export function railDestinations(): RailItem[] {
  const rows = menuDestinations();
  if (!railItemVisible(WARROOM_ROW)) return rows;
  const at = rows.findIndex((r) => r.id === 'dashboards');
  return at === -1 ? [WARROOM_ROW, ...rows] : [...rows.slice(0, at + 1), WARROOM_ROW, ...rows.slice(at + 1)];
}

export function railZoneItems(): { top: RailItem[]; bottom: RailItem[] } {
  const settings = menuSettings();
  const topDefault = [...menuLeadItems(), ...menuDestinations()];
  const bottomDefault = [...menuHelpLinks(), ...(settings ? [settings] : [])];
  const byId = new Map([...topDefault, ...bottomDefault].map((item) => [item.id, item]));
  const ids = resolveRailZones(topDefault, bottomDefault, storedMenuOrder());
  const items = (list: string[]): RailItem[] => list.map((id) => byId.get(id) as RailItem);
  const zones = { top: items(ids.top), bottom: items(ids.bottom) };
  if (!railItemVisible(WARROOM_ROW)) return zones;
  const home = zones.top.some((r) => r.id === 'dashboards') ? zones.top : zones.bottom.some((r) => r.id === 'dashboards') ? zones.bottom : zones.top;
  const at = home.findIndex((r) => r.id === 'dashboards');
  home.splice(at === -1 ? 0 : at + 1, 0, WARROOM_ROW);
  return zones;
}
