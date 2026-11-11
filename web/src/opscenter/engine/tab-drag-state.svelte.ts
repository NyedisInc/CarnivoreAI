import type { TabDrop } from './tab-drag';

export const tabDrag: { tab: string | null; target: TabDrop | null } = $state({
  tab: null,
  target: null,
});

export function dropIndexFor(slot: string): number | null {
  const target = tabDrag.target;
  return target && target.kind === 'strip' && target.slot === slot ? target.index : null;
}
