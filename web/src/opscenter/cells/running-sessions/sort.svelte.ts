
import { elapsedSeconds, normalizeStatus, type ProjectResponse, type SessionInfo } from '../../api';
import { createSortPref } from '../../lib/list-sort.svelte';
import { projectOfRow } from './project';
import { taskFor } from './meta';

export type SortKey = 'activity' | 'name' | 'last_used' | 'project';

export const SORT_KEYS: readonly SortKey[] = ['activity', 'name', 'last_used', 'project'];

export const SORT_KEY_DEFAULT: SortKey = 'activity';

export const RUNNING_SESSIONS_SORT_KEY = 'carnivore.opscenter.runningSessions.sort';

export function statusPriority(row: SessionInfo): number {
  if (row.startup_gate === 'awaiting_startup_prompt') return 1;
  const key = normalizeStatus(row.activity_status);
  if (row.unread === true && (key === 'idle' || key === 'unknown')) return 3;
  switch (key) {
    case 'working':
    case 'working_subagent':
    case 'running':
      return 0;
    case 'question':
      return 1;
    case 'notice':
      return 2;
    case 'finished_unread':
      return 3;
    case 'idle':
      return 4;
    case 'unknown':
      return 5;
    default:
      return 6;
  }
}

function sinceLastActivity(row: SessionInfo, now: number): number {
  const seconds = elapsedSeconds(row.session.last_activity, now);
  return seconds === null ? Number.POSITIVE_INFINITY : seconds;
}

export function sortRows(
  rows: readonly SessionInfo[],
  key: SortKey,
  projectRows: readonly ProjectResponse[],
  now: number,
): SessionInfo[] {
  const copy = rows.slice();
  switch (key) {
    case 'name':
      copy.sort((a, b) => taskFor(a).localeCompare(taskFor(b)));
      break;
    case 'last_used':
      copy.sort((a, b) => sinceLastActivity(a, now) - sinceLastActivity(b, now));
      break;
    case 'project':
      copy.sort((a, b) => {
        const byProject = projectOfRow(a, projectRows).localeCompare(
          projectOfRow(b, projectRows),
        );
        return byProject !== 0 ? byProject : taskFor(a).localeCompare(taskFor(b));
      });
      break;
    case 'activity':
    default:
      copy.sort((a, b) => {
        const byStatus = statusPriority(a) - statusPriority(b);
        return byStatus !== 0 ? byStatus : sinceLastActivity(a, now) - sinceLastActivity(b, now);
      });
      break;
  }
  return copy;
}

export const runningSessionsSortPref = createSortPref(RUNNING_SESSIONS_SORT_KEY, SORT_KEYS, SORT_KEY_DEFAULT);
