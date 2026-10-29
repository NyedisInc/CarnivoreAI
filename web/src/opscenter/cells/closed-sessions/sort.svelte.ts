/* recently closed sessions */

import type { SessionRecord } from '../../api';
import { createSortPref } from '../../lib/list-sort.svelte';
import { taskFor } from './meta';

export type SortKey = 'recent' | 'name';

export const SORT_KEYS: readonly SortKey[] = ['recent', 'name'];

export const SORT_KEY_DEFAULT: SortKey = 'recent';

export const CLOSED_SESSIONS_SORT_KEY = 'carnivore.opscenter.closedSessions.sort';

export function sortRows(rows: readonly SessionRecord[], key: SortKey): SessionRecord[] {
  const copy = rows.slice();
  switch (key) {
    case 'name':
      copy.sort((a, b) => taskFor(a).localeCompare(taskFor(b)));
      break;
    case 'recent':
    default:
      break;
  }
  return copy;
}

export const closedSessionsSortPref = createSortPref(CLOSED_SESSIONS_SORT_KEY, SORT_KEYS, SORT_KEY_DEFAULT);
