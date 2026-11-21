import type { Payload } from './payload-model';

const LAYER_VERSION = 1;
const MAX_SHORT_TEXT = 300;
const MAX_LONG_TEXT = 4000;
const MAX_NOTE = 4000;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export interface LayerOption { id: string }
export interface LayerItem { id: string; kind: string; options?: LayerOption[]; min?: number | string | null; max?: number | string | null }
export interface LayerRow { id: string; choices?: LayerOption[] | null }
export interface BoardLayer { kind: 'questions' | 'rows'; items?: LayerItem[]; rows?: LayerRow[]; choices?: LayerOption[] | null; pick?: 'one' | 'several' }

function distinctSubset(value: unknown, ids: readonly string[]): value is string[] {
  return Array.isArray(value) && new Set(value).size === value.length && value.every((v) => typeof v === 'string' && ids.includes(v));
}

function within(value: number | string, min: unknown, max: unknown): boolean {
  return (min == null || value >= (min as number | string)) && (max == null || value <= (max as number | string));
}

function fitsItem(item: LayerItem, value: unknown): boolean {
  const ids = (item.options ?? []).map((o) => o.id);
  switch (item.kind) {
    case 'yesno':
    case 'toggle':
      return typeof value === 'boolean';
    case 'choice':
      return typeof value === 'string' && ids.includes(value);
    case 'multi':
      return distinctSubset(value, ids) && (item.max == null || value.length <= Number(item.max));
    case 'rank':
      return Array.isArray(value) && value.every((v) => typeof v === 'string') && [...value].sort().join('\n') === [...ids].sort().join('\n');
    case 'text':
      return typeof value === 'string' && value.length <= MAX_SHORT_TEXT;
    case 'longtext':
      return typeof value === 'string' && value.length <= MAX_LONG_TEXT;
    case 'number':
      return typeof value === 'number' && Number.isFinite(value) && within(value, item.min, item.max);
    case 'date':
      return typeof value === 'string' && DAY.test(value) && !Number.isNaN(Date.parse(value)) && within(value, item.min, item.max);
    default:
      return false;
  }
}

function fitsRow(layer: BoardLayer, row: LayerRow, value: unknown): boolean {
  const ids = (row.choices ?? layer.choices ?? []).map((c) => c.id);
  return layer.pick === 'several' ? distinctSubset(value, ids) : typeof value === 'string' && ids.includes(value);
}

export function fitsLayer(layer: BoardLayer, payload: Payload): boolean {
  if (Object.keys(payload).some((k) => !['layer', 'v', 'values', 'notes'].includes(k))) return false;
  if (payload.layer !== layer.kind || payload.v !== LAYER_VERSION) return false;
  const values = payload.values;
  const notes = payload.notes ?? {};
  if (values === null || typeof values !== 'object' || Array.isArray(values)) return false;
  if (notes === null || typeof notes !== 'object' || Array.isArray(notes)) return false;
  const known = new Map<string, LayerItem | LayerRow>([...(layer.items ?? []), ...(layer.rows ?? [])].map((i) => [i.id, i]));
  for (const [id, value] of Object.entries(values as Record<string, unknown>)) {
    const target = known.get(id);
    if (!target) return false;
    if (!(layer.kind === 'questions' ? fitsItem(target as LayerItem, value) : fitsRow(layer, target as LayerRow, value))) return false;
  }
  return Object.entries(notes as Record<string, unknown>).every(([id, text]) => known.has(id) && typeof text === 'string' && text.length <= MAX_NOTE);
}
