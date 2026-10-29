import type { TabDrop } from './tab-drag';
import type { Zone } from './tab-split';

export const tabDrag: { tab: string | null; target: TabDrop | null; zone: { slot: string; zone: Zone } | null } = $state({
  tab: null,
  target: null,
  zone: null,
});

export function dropIndexFor(slot: string): number | null {
  const target = tabDrag.target;
  return target && target.kind === 'strip' && target.slot === slot ? target.index : null;
}

export function zoneFor(slot: string): Zone | null {
  return tabDrag.zone?.slot === slot ? tabDrag.zone.zone : null;
}
