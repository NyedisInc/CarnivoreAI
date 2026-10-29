
import { metaFor } from '../../engine/meta';
import { projects } from '../../api';
import type { ColumnSpec } from '../../engine/types';

export const meta = metaFor('projects');

export const columns: ColumnSpec[] = [
  { key: 'name', headKey: 'opscenter.column.name', minPx: 150, weight: 2.24, insetPx: 19 },
  { key: 'type', headKey: 'opscenter.column.root', minPx: 98, weight: 1.05, insetPx: 11 },
  { key: 'updated', headKey: 'opscenter.column.updated', minPx: 88, weight: 1.34, insetPx: 15 },
  { key: 'sessions', headKey: 'opscenter.column.sessions', minPx: 154, weight: 1, align: 'end' },
  { key: 'path', headKey: 'opscenter.column.path', minPx: 180, weight: 2 },
];

export const COLUMNS_AT: Readonly<Record<string, readonly string[]>> = {
  name: ['name'],
  updated: ['name', 'updated'],
  type: ['name', 'type', 'updated'],
  sessions: ['name', 'type', 'updated', 'sessions'],
  path: ['name', 'type', 'updated', 'sessions', 'path'],
};

export const phoneColumns: ColumnSpec[] = [
  { key: 'name', headKey: '', minPx: 0, weight: 1, line: 1 },
  { key: 'phoneSessions', headKey: '', minPx: 0, weight: 0, align: 'end', line: 1 },
  { key: 'phonePath', headKey: '', minPx: 0, weight: 1, line: 2 },
];

export function titleCount(): number | null {
  return projects.status === 'ok' ? (projects.data?.length ?? null) : null;
}

export function phoneTotal(): number | null {
  return titleCount();
}
