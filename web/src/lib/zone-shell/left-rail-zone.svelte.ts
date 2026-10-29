import { railEntries } from '../sidebar-widgets/rail-model';
import { activeFlyout, pressRail } from '../sidebar-widgets/flyout.svelte';
import type { SidebarWidget } from '../sidebar-widgets/types';
import { createZone, type Zone } from './zone.svelte';
import type { TabRef } from './zone-types';

export const LEFT_RAIL_ZONE_KEY = 'rail:left';

const drawn = $state<{ id: string | null }>({ id: null });

export function setDrawnFlyout(id: string | null): void {
  drawn.id = id;
}

export function leftRailWidgets(): SidebarWidget[] {
  const all = railEntries();
  return [...all.fixed, ...all.registered];
}

let zone: Zone | null = null;

export function leftRailZone(): Zone {
  zone ??= createZone({
    key: LEFT_RAIL_ZONE_KEY,
    tabs: (): readonly TabRef[] => leftRailWidgets().map((widget) => ({ key: widget.id, kind: 'panel' })),
    active: () => drawn.id ?? activeFlyout(),
    select: (key) => void pressRail(key),
    panel: () => (activeFlyout() === null ? 'closed' : 'open'),
    strip: 'keys',
    toolbar: 'header',
    menuHost: 'section-head',
  });
  return zone;
}
