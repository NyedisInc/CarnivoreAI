
import type { ProjectResponse } from '../../api';
import { parseServerTime } from '../../lib/format';
import { createSortPref } from '../../lib/list-sort.svelte';

export type SortKey = 'last_used' | 'name';

export const SORT_KEYS: readonly SortKey[] = ['last_used', 'name'];

export const SORT_KEY_DEFAULT: SortKey = 'last_used';

export const PROJECTS_SORT_KEY = 'carnivore.opscenter.projects.sort';

function sinceWorkedOn(row: ProjectResponse, now: number): number {
  if (!row.work_at) return Number.POSITIVE_INFINITY;
  const at = parseServerTime(row.work_at);
  return Number.isFinite(at) ? Math.max(0, now - at) : Number.POSITIVE_INFINITY;
}

export function sortRows<T extends ProjectResponse>(rows: readonly T[], key: SortKey, now: number): T[] {
  const copy = rows.slice();
  switch (key) {
    case 'name':
      copy.sort((a, b) => a.name.localeCompare(b.name));
      break;
    case 'last_used':
    default:
      copy.sort((a, b) => sinceWorkedOn(a, now) - sinceWorkedOn(b, now));
      break;
  }
  return copy;
}

export const projectsSortPref = createSortPref(PROJECTS_SORT_KEY, SORT_KEYS, SORT_KEY_DEFAULT);
