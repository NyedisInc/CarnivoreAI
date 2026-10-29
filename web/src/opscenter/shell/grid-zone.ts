/*  hidden  */
import { createZone, type Zone } from '../../lib/zone-shell/zone.svelte';
import type { PanelState, TabRef } from '../../lib/zone-shell/zone-types';

export function gridZoneKey(slot: string): string {
  return `grid:${slot}`;
}

export function gridTabKey(slot: string): string {
  return slot.split(':')[0] || slot;
}

export function gridHeaderId(slot: string): string {
  return `${gridZoneKey(slot)}#${gridTabKey(slot)}`;
}

export function createGridZone(slot: string, panel: () => PanelState): Zone {
  const tab: TabRef = { key: gridTabKey(slot), kind: gridTabKey(slot) === 'terminal' ? 'terminal' : 'widget' };
  const tabs: readonly TabRef[] = [tab];
  return createZone({
    key: gridZoneKey(slot),
    tabs: () => tabs,
    active: () => tab.key,
    select: () => {},
    panel,
    strip: 'none',
    toolbar: 'header',
    menuHost: 'grid',
    headerId: () => gridHeaderId(slot),
    seedHeader: (header) => {
      header.gridSlot = slot;
    },
  });
}
