
import { metaFor } from '../../engine/meta';
import { catalog, byKind, indexNotice, refreshIndex } from '../../api';
import type { ColumnSpec } from '../../engine/types';

export const meta = metaFor('skills');

export const columns: ColumnSpec[] = [
  { key: 'name', headKey: 'opscenter.column.name', minPx: 140, weight: 2, insetPx: 17 },
  { key: 'description', headKey: 'opscenter.column.description', minPx: 220, weight: 2.8, insetPx: 14 },
  { key: 'author', headKey: 'opscenter.column.author', minPx: 140, weight: 1 },
  { key: 'version', headKey: 'opscenter.column.version', minPx: 110, weight: 1 },
];

export const COLUMNS_AT: Readonly<Record<string, readonly string[]>> = {
  name: ['name'],
  description: ['name', 'description'],
  author: ['name', 'description', 'author'],
  version: ['name', 'description', 'author', 'version'],
  full: ['name', 'description', 'author', 'version'],
};

export const phoneColumns: ColumnSpec[] = [{ key: 'name', headKey: '', minPx: 0, weight: 1, line: 1 }];

export function titleCount(): number | null {
  if (catalog.status !== 'ok' || !catalog.data) return null;
  const untrusted = catalog.data.untrusted.filter((item) => item.kind === 'skill').length;
  return byKind(catalog.data, 'skill').length + untrusted;
}

/* there is nothing */
export function titleSuffix(): string | null {
  if (catalog.status !== 'ok') return null;
  return indexNotice(catalog.data) || null;
}

let refreshing = false;
export function onRightControl(): void {
  if (refreshing) return;
  refreshing = true;
  void refreshIndex().finally(() => {
    refreshing = false;
  });
}

export function phoneTotal(): number | null {
  return titleCount();
}
