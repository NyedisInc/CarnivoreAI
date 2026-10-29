import type { Bar, Gap, Mark } from './types';

export const PAD_PX = 8;
export const COLUMN_CONTENT_PLOT_PX = 420;
export const COLUMN_MIN_PLOT_PX = 240;
export const COLUMN_DETAIL_SHARE = 0.28;
export const COLUMN_DETAIL_MIN_PX = 150;
export const COLUMN_DETAIL_MAX_PX = 260;
export const COLUMN_INSET_PX = 8;
/* waiting on you */
export const WAITING_KINDS: readonly string[] = ['question', 'startup'];

export type Body = 'list' | 'column';

export type PointAction = 'branch' | 'rewind' | 'bookmark' | 'copy' | 'open';

export interface Frame {
  body: Body;
  plotPx: number;
  detailPx: number;
  pad: number;
}

export function frameFor(phone: boolean, height: number | null): Frame {
  if (phone) return { body: 'list', plotPx: 0, detailPx: 0, pad: PAD_PX };
  const detailPx = height === null ? COLUMN_DETAIL_MIN_PX
    : Math.round(Math.min(COLUMN_DETAIL_MAX_PX, Math.max(COLUMN_DETAIL_MIN_PX, height * COLUMN_DETAIL_SHARE)));
  const plotPx = height === null ? COLUMN_CONTENT_PLOT_PX : Math.max(COLUMN_MIN_PLOT_PX, height - 3 * PAD_PX - detailPx - 2 * COLUMN_INSET_PX);
  return { body: 'column', plotPx, detailPx, pad: PAD_PX };
}

export interface Seg {
  bar: Bar;
  index: number;
  x0: number;
  x1: number;
}

export type Item =
  | { key: string; kind: 'conversation'; bar: Bar; index: number; x: number }
  | { key: string; kind: 'mark'; mark: Mark; x: number }
  | { key: string; kind: 'cluster'; marks: Mark[]; x: number }
  | { key: string; kind: 'sleep'; gap: Gap; x: number; x1: number };

/* waiting on you */
export interface Band {
  key: string;
  state: 'busy' | 'idle' | 'waiting';
  x0: number;
  x1: number;
}

export interface Hook {
  key: string;
  kind: string;
  fromX: number;
  toX: number;
}

export function clusterMarks(points: ReadonlyArray<{ mark: Mark; x: number }>, minPx: number): Item[] {
  const groups: Array<{ marks: Mark[]; xs: number[] }> = [];
  const mean = (g: { xs: number[] }): number => g.xs.reduce((s, v) => s + v, 0) / g.xs.length;
  for (const p of [...points].sort((a, b) => a.x - b.x)) {
    const last = groups[groups.length - 1];
    if (last && p.x - mean(last) < minPx) { last.marks.push(p.mark); last.xs.push(p.x); }
    else groups.push({ marks: [p.mark], xs: [p.x] });
  }
  for (let i = 1; i < groups.length; ) {
    if (mean(groups[i]!) - mean(groups[i - 1]!) < minPx) {
      groups[i - 1]!.marks.push(...groups[i]!.marks);
      groups[i - 1]!.xs.push(...groups[i]!.xs);
      groups.splice(i, 1);
      i = Math.max(1, i - 1);
    } else i += 1;
  }
  return groups.map((g): Item => (g.marks.length === 1
    ? { key: `mark:${g.marks[0]!.id}`, kind: 'mark', mark: g.marks[0]!, x: mean(g) }
    : { key: `cluster:${g.marks[0]!.id}`, kind: 'cluster', marks: g.marks, x: mean(g) }));
}

export type Move = 'left' | 'right' | 'up' | 'down' | 'home' | 'end';
