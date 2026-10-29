import { authFetch } from '../../opscenter/api/auth.svelte';
import { scheduleFields, type EditorDraft } from '../../cplugs/huddle/task-manager-schedule';
import type { TaskManagerSchedule } from './task-manager-scheduled';

export type Fetcher = typeof authFetch;

const ITEMS = '/cplugs/huddle/items';

export type WritableSchedule = TaskManagerSchedule & { source: NonNullable<TaskManagerSchedule['source']> };

export function isWritable(schedule: TaskManagerSchedule): schedule is WritableSchedule {
  return Boolean(schedule.source);
}

export function setPaused(schedule: WritableSchedule, paused: boolean, fetcher: Fetcher = authFetch): Promise<unknown> {
  return fetcher(`${ITEMS}/${schedule.item}`, { method: 'PATCH', body: JSON.stringify({ paused, expected_revision: schedule.source.revision }) });
}

export function saveSchedule(schedule: WritableSchedule, draft: EditorDraft, fetcher: Fetcher = authFetch): Promise<unknown> {
  const fields = scheduleFields(draft, Boolean(schedule.repeat));
  if (!fields) return Promise.reject(new Error('invalid_schedule'));
  return fetcher(`${ITEMS}/${schedule.item}`, { method: 'PATCH', body: JSON.stringify({ ...fields, expected_revision: schedule.source.revision }) });
}

export function deleteItem(schedule: WritableSchedule, fetcher: Fetcher = authFetch): Promise<unknown> {
  return fetcher(`${ITEMS}/${schedule.item}`, { method: 'DELETE' });
}
