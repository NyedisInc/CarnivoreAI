import { WIDGET_TYPES, type WidgetType } from '../widgets/types';
import type { GroupRow } from './drawer-groups';
import { fuzzyMatch } from './drawer-fuzzy';

export type DrawerViewMode = 'type' | 'name';

export const DRAWER_VIEW_MODES: readonly DrawerViewMode[] = ['type', 'name'];

export const DEFAULT_DRAWER_VIEW: DrawerViewMode = 'type';

const WORD_MATCH_FLOOR = -1000;

export interface ViewRow {
  row: GroupRow;
  indices: number[];
  score: number;
}

export interface TypeSection {
  type: WidgetType;
  rows: ViewRow[];
}

export interface DrawerView {
  mode: DrawerViewMode;
  flat: ViewRow[];
  sections: TypeSection[];
}

export function isDrawerViewMode(value: unknown): value is DrawerViewMode {
  return typeof value === 'string' && (DRAWER_VIEW_MODES as readonly string[]).includes(value);
}

const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });

function byName(a: GroupRow, b: GroupRow): number {
  return collator.compare(a.title, b.title) || collator.compare(a.widgetId, b.widgetId);
}

function rank(row: GroupRow, query: string, words: readonly string[]): ViewRow | null {
  const named = fuzzyMatch(query, row.title);
  if (named) return { row, indices: named.indices, score: named.score };
  let top: number | null = null;
  for (const word of words) {
    const hit = fuzzyMatch(query, word);
    if (hit && (top === null || hit.score > top)) top = hit.score;
  }
  return top === null ? null : { row, indices: [], score: WORD_MATCH_FLOOR + top };
}

export function arrange(rows: readonly GroupRow[], query: string, words: (row: GroupRow) => readonly string[]): ViewRow[] {
  const needle = query.trim();
  if (!needle) return [...rows].sort(byName).map((row) => ({ row, indices: [], score: 0 }));
  const ranked: ViewRow[] = [];
  for (const row of rows) {
    const one = rank(row, needle, words(row));
    if (one) ranked.push(one);
  }
  return ranked.sort((a, b) => b.score - a.score || byName(a.row, b.row));
}

export function buildView(
  rows: readonly GroupRow[],
  mode: DrawerViewMode,
  query: string,
  words: (row: GroupRow) => readonly string[],
  typeLabel: (type: WidgetType) => string = (type) => type,
): DrawerView {
  const arranged = arrange(rows, query, words);
  if (mode === 'name') return { mode, flat: arranged, sections: [] };
  const sections = [...WIDGET_TYPES]
    .sort((a, b) => collator.compare(typeLabel(a), typeLabel(b)) || collator.compare(a, b))
    .map((type) => ({ type, rows: arranged.filter((one) => one.row.type === type) })).filter(
    (section) => section.rows.length > 0,
  );
  return { mode, flat: [], sections };
}

export function toggleFold(folded: ReadonlySet<WidgetType>, type: WidgetType, all: readonly WidgetType[], cascade: boolean): Set<WidgetType> {
  const folding = !folded.has(type);
  if (!cascade) {
    const next = new Set(folded);
    if (folding) next.add(type);
    else next.delete(type);
    return next;
  }
  return folding ? new Set(all) : new Set();
}

export function isOpen(folded: ReadonlySet<WidgetType>, type: WidgetType, query: string): boolean {
  return query.trim() !== '' || !folded.has(type);
}
