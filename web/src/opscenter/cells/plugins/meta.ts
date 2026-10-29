
import { metaFor } from '../../engine/meta';
import { PLUGIN_REGISTRY } from './registry-mirror';
import type { ColumnSpec } from '../../engine/types';

export const meta = metaFor('plugins');

export const columns: ColumnSpec[] = [
  { key: 'name', headKey: 'opscenter.column.name', minPx: 150, weight: 1.69, insetPx: 15 },
  { key: 'surfaces', headKey: 'opscenter.column.surfaces', minPx: 216, weight: 2.85 },
  { key: 'contributions', headKey: 'opscenter.column.contributions', minPx: 144, weight: 1, align: 'end' },
];

export const COLUMNS_AT: Readonly<Record<string, readonly string[]>> = {
  name: ['name'],
  description: ['name', 'surfaces'],
  version: ['name', 'surfaces', 'contributions'],
};

export const phoneColumns: ColumnSpec[] = [
  { key: 'name', headKey: '', minPx: 0, weight: 1, line: 1 },
  { key: 'phoneSurface', headKey: '', minPx: 0, weight: 0, align: 'end', line: 1 },
];

export function titleCount(): number | null {
  return PLUGIN_REGISTRY.length;
}

export function phoneTotal(): number | null {
  return titleCount();
}
