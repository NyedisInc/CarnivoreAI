/* scheduled tasks */

import { metaFor } from '../../engine/meta';
import type { ColumnSpec } from '../../engine/types';
import { scheduledTasks } from '../../api/scheduled-tasks.svelte';

export const meta = metaFor('scheduled-tasks');

export const columns: ColumnSpec[] = [
  { key: 'name', headKey: 'opscenter.column.name', minPx: 130, weight: 2, insetPx: 12 },
  { key: 'description', headKey: 'opscenter.column.description', minPx: 150, weight: 2.4 },
  { key: 'schedule', headKey: 'opscenter.column.schedule', minPx: 90, weight: 1 },
  { key: 'lastRun', headKey: 'opscenter.column.last_run', minPx: 72, weight: 0.6, align: 'end' },
];

export const COLUMNS_AT: Readonly<Record<string, readonly string[]>> = {
  name: ['name', 'lastRun'],
  description: ['name', 'description', 'lastRun'],
  full: ['name', 'description', 'schedule', 'lastRun'],
};

export const phoneColumns: ColumnSpec[] = [
  { key: 'name', headKey: '', minPx: 0, weight: 1, line: 1 },
  { key: 'lastRun', headKey: '', minPx: 0, weight: 0, align: 'end', line: 1 },
];

export function titleCount(): number | null {
  const current = scheduledTasks();
  if (!current || current.status !== 'ok' || !current.data || current.data.state !== 'ok') return null;
  return current.data.total;
}

export function phoneTotal(): number | null {
  const current = scheduledTasks();
  if (!current || current.status !== 'ok' || !current.data) return null;
  return current.data.tasks.length;
}
