import { createZone, type Zone } from '../zone.svelte';
import type { PanelState, TabRef } from '../zone-types';

export const world = $state({
  tabs: [] as TabRef[],
  active: null as string | null,
  panel: 'open' as PanelState,
  selected: [] as string[],
});

export function resetWorld(): void {
  world.tabs = [
    { key: 'a', kind: 'panel' },
    { key: 'b', kind: 'panel' },
  ];
  world.active = 'a';
  world.panel = 'open';
  world.selected = [];
}

export function worldZone(): Zone {
  return createZone({
    key: 'test:zone',
    tabs: () => world.tabs,
    active: () => world.active,
    select: (key) => {
      world.selected.push(key);
      world.active = key;
    },
    panel: () => world.panel,
    strip: 'keys',
    toolbar: 'strip',
    menuHost: 'tab',
  });
}
