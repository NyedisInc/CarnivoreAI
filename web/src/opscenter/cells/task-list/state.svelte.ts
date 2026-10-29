import { holdAggregate, huddle, startTaskManager } from '../../../cplugs/huddle/huddle.svelte';
import type { PlacementOptions } from '../../widgets/placement-options';
import { listRows, type ListRow } from './model';

export function holdList(): () => void {
  startTaskManager();
  return holdAggregate();
}

export function listRowsFor(options?: PlacementOptions): ListRow[] {
  return listRows(huddle.groups, options);
}

export function listCount(options?: PlacementOptions): number | null {
  return huddle.groups === null ? null : listRowsFor(options).length;
}
