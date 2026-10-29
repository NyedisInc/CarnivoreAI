/* and writes nothing */
import { leftRailZone } from '../zone-shell/left-rail-zone.svelte';
import type { Zone } from '../zone-shell/zone.svelte';
import { drawerCardZones } from '../drawer-zone/area-zones';
import { rootZone } from './root-zone.svelte';

export interface DrawerLayout {
  readonly root: Zone;
  readonly leftRail: Zone;
  readonly cards: readonly Zone[];
}

export function drawerLayout(): DrawerLayout {
  return {
    root: rootZone(),
    leftRail: leftRailZone(),
    get cards() {
      return drawerCardZones();
    },
  };
}
