import type { Bar, Filters, FilterKey, Gap, Mark, MarkKind, SessionTimeline } from './types';

export const FILTER_KEYS: readonly FilterKey[] = ['bookmarks', 'compacts', 'restarts', 'sleeps', 'restores'];

export const ALL_FILTERS_ON: Readonly<Filters> = Object.freeze({ bookmarks: true, compacts: true, restarts: true, sleeps: true, restores: true });

const FILTER_OF_KIND: Readonly<Record<MarkKind, FilterKey>> = { bookmark: 'bookmarks', compact: 'compacts', restart: 'restarts', restore: 'restores' };

export const SPLIT_KINDS: readonly string[] = ['fork', 'rewind', 'resume', 'branch'];

export function timeMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

export function visibleMarks(data: SessionTimeline, filters: Filters): Mark[] {
  return data.marks.filter((mark) => filters[FILTER_OF_KIND[mark.kind]]);
}

export function visibleGaps(data: SessionTimeline, filters: Filters): Gap[] {
  return filters.sleeps ? data.gaps : [];
}

export function filterCounts(data: SessionTimeline): Record<FilterKey, number> {
  const counts: Record<FilterKey, number> = { bookmarks: 0, compacts: 0, restarts: 0, sleeps: data.gaps.length, restores: 0 };
  for (const mark of data.marks) counts[FILTER_OF_KIND[mark.kind]] += 1;
  return counts;
}

export type ListRow =
  | { key: string; type: 'began'; at: string | null; bar: Bar; index: number }
  | { key: string; type: 'mark'; at: string | null; mark: Mark }
  | { key: string; type: 'gap'; at: string | null; gap: Gap };

export function phoneRows(data: SessionTimeline, filters: Filters): ListRow[] {
  const startOf = new Map(data.bars.map((b): [string, number] => [b.conversation_id, timeMs(b.started_at) ?? 0]));
  const rows: Array<ListRow & { t: number; rank: number }> = [];
  data.bars.forEach((bar, index) => rows.push({ key: `bar:${bar.conversation_id}`, type: 'began', at: bar.started_at, bar, index, t: startOf.get(bar.conversation_id) ?? 0, rank: 0 }));
  for (const mark of visibleMarks(data, filters)) rows.push({ key: mark.id, type: 'mark', at: mark.at, mark, t: timeMs(mark.at) ?? startOf.get(mark.conversation_id) ?? 0, rank: 1 });
  for (const gap of visibleGaps(data, filters)) rows.push({ key: gap.id, type: 'gap', at: gap.start, gap, t: timeMs(gap.start) ?? startOf.get(gap.conversation_id) ?? 0, rank: 1 });
  rows.sort((a, b) => a.t - b.t || a.rank - b.rank);
  return rows.map(({ t: _t, rank: _rank, ...row }) => row as ListRow);
}
