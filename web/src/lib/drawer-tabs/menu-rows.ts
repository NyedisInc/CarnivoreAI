import { RAIL_DESTINATIONS, WARROOM_ROW, railItemVisible, type RailItem } from '../../opscenter/shell/rail-items';
import { activeFlyout, pressRail } from '../sidebar-widgets/flyout.svelte';
import { railEntries } from '../sidebar-widgets/rail-model';
import { MENU_FLYOUT, SESSION_LIST_WIDGET, SWARM_FLYOUT } from '../sidebar-widgets/widget-ids';
import { orderedMenuItems } from './menu-order.svelte';

export function menuLeadItems(): RailItem[] {
  const { fixed, registered } = railEntries();
  const swarmFirst = [...registered].sort((a, b) => Number(b.id === SWARM_FLYOUT) - Number(a.id === SWARM_FLYOUT));
  return [...fixed.filter((w) => w.id !== MENU_FLYOUT), ...swarmFirst].map((w) => ({
    id: w.id,
    icon: w.icon,
    labelKey: w.titleKey,
    hint: '',
    widgetId: w.id,
    badge: w.badge,
    close: w.close,
    pressed: w.action ? undefined : () => (w.id === SESSION_LIST_WIDGET ? activeFlyout() === null : activeFlyout() === w.id),
    run: () => void pressRail(w.id),
  }));
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
