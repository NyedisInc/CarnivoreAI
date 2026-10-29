import { SPLIT_KINDS, timeMs, visibleGaps, visibleMarks } from './model';
import type { Filters, Mark, SessionTimeline } from './types';
import { clusterMarks, WAITING_KINDS, type Band, type Hook, type Item, type Seg } from './plot-model';
import { buildScale, rulerTicks, type Tick } from './scale';

export const CLUSTER_V_PX = 12;
export const LABEL_PX = 16;
export const RULER_PX = 54;
export const RAIL_COL_PX = 44;
export const RAIL_X = 33;
export const BAND_X = 25;
export const HOOK_X0 = 20;
export const HOOK_STEP = 5;
export const HOOK_TRACKS = 3;
const KEEP_ORDER: Readonly<Record<string, number>> = { conversation: 0, cluster: 1, bookmark: 2, compact: 3, restart: 4, restore: 5 };

export interface ColumnItem {
  item: Item;
  y: number;
  labelTop: number | null;
}

export interface ColumnHook extends Hook {
  track: number;
}

export interface Column {
  plotPx: number;
  segs: Seg[];
  items: ColumnItem[];
  bands: Band[];
  hooks: ColumnHook[];
  ticks: Tick[];
  ordered: boolean;
}

export function placeLabels(anchors: ReadonlyArray<{ key: string; y: number; keep: number }>, height: number, rowPx: number): Map<string, number> {
  const room = Math.max(0, Math.floor(height / rowPx));
  const kept = [...anchors].sort((a, b) => a.keep - b.keep || a.y - b.y).slice(0, room).sort((a, b) => a.y - b.y);
  const tops = kept.map((a) => a.y - rowPx / 2);
  for (let i = 0; i < tops.length; i += 1) tops[i] = Math.max(tops[i]!, i === 0 ? 0 : tops[i - 1]! + rowPx);
  for (let i = tops.length - 1; i >= 0; i -= 1) tops[i] = Math.min(tops[i]!, i === tops.length - 1 ? height - rowPx : tops[i + 1]! - rowPx);
  for (let i = 0; i < tops.length; i += 1) tops[i] = Math.max(tops[i]!, i === 0 ? 0 : tops[i - 1]! + rowPx);
  return new Map(kept.map((a, i) => [a.key, tops[i]!]));
}

export function layoutColumn(data: SessionTimeline, filters: Filters, plotPx: number, squeeze: boolean): Column {
  const scale = buildScale(data, plotPx, squeeze);
  const n = data.bars.length;
  const segs: Seg[] = data.bars.map((bar, index) => {
    if (!scale) return { bar, index, x0: (index * plotPx) / n + (index > 0 ? 2 : 0), x1: ((index + 1) * plotPx) / n - 2 };
    const y0 = scale.x(timeMs(bar.started_at)!);
    return { bar, index, x0: y0 + (index > 0 ? 1 : 0), x1: Math.max(y0 + 4, scale.x(timeMs(bar.ended_at)!) - 1) };
  });
  const segOf = new Map(segs.map((s) => [s.bar.conversation_id, s]));

  const perBar = new Map<string, Mark[]>();
  for (const mark of visibleMarks(data, filters)) if (segOf.has(mark.conversation_id)) perBar.set(mark.conversation_id, [...(perBar.get(mark.conversation_id) ?? []), mark]);
  const points: Array<{ mark: Mark; x: number }> = [];
  for (const [id, marks] of perBar) {
    const seg = segOf.get(id)!;
    marks.forEach((mark, i) => {
      const at = timeMs(mark.at);
      const y = scale && at !== null ? scale.x(at) : seg.x0 + ((i + 1) / (marks.length + 1)) * (seg.x1 - seg.x0);
      points.push({ mark, x: Math.min(seg.x1, Math.max(seg.x0, y)) });
    });
  }
  const items: Item[] = [
    ...segs.map((s): Item => ({ key: `conv:${s.bar.conversation_id}`, kind: 'conversation', bar: s.bar, index: s.index, x: s.x0 })),
    ...(scale ? visibleGaps(data, filters) : []).flatMap((gap): Item[] => {
      const seg = segOf.get(gap.conversation_id);
      const from = timeMs(gap.start);
      const to = gap.end === null ? timeMs(data.now) : timeMs(gap.end);
      if (!seg || from === null || to === null) return [];
      const y = Math.max(seg.x0, scale!.x(from));
      return [{ key: `sleep:${gap.id}`, kind: 'sleep', gap, x: y, x1: Math.max(y + 3, Math.min(seg.x1, scale!.x(to))) }];
    }),
    ...clusterMarks(points, CLUSTER_V_PX),
  ];
  const rank = (i: Item): number => (i.kind === 'conversation' ? 0 : i.kind === 'sleep' ? 1 : 2);
  items.sort((a, b) => a.x - b.x || rank(a) - rank(b));

  const keepOf = (i: Item): number => KEEP_ORDER[i.kind === 'mark' ? i.mark.kind : i.kind] ?? 9;
  const tops = placeLabels(items.filter((i) => i.kind !== 'sleep').map((i) => ({ key: i.key, y: i.x, keep: keepOf(i) })), plotPx, LABEL_PX);

  const nowMs = timeMs(data.now) ?? 0;
  const bands: Band[] = [];
  for (const seg of scale ? segs : []) {
    const clip = (from: number | null, to: number | null): [number, number] | null => {
      if (from === null || to === null) return null;
      const a = Math.max(seg.x0, scale!.x(from));
      const b = Math.min(seg.x1, scale!.x(to));
      return b > a ? [a, b] : null;
    };
    for (const run of seg.bar.activity ?? []) {
      const span = clip(timeMs(run.start), timeMs(run.end));
      if (span) bands.push({ key: `run:${run.start}:${run.state}`, state: run.state, x0: span[0], x1: span[1] });
    }
    for (const a of data.attention ?? []) {
      if (!WAITING_KINDS.includes(a.kind)) continue;
      const span = clip(timeMs(a.start), a.end === null ? nowMs : timeMs(a.end));
      if (span) bands.push({ key: `wait:${a.start}:${seg.bar.conversation_id}`, state: 'waiting', x0: span[0], x1: span[1] });
    }
  }

  const hooks: ColumnHook[] = [];
  const trackEnds: number[] = [];
  for (const child of segs) {
    const began = child.bar.began;
    const split = began?.split;
    const parent = split ? segOf.get(split.conversation ?? began?.from_conversation ?? '') : undefined;
    if (!began || !split || !parent || parent === child || !SPLIT_KINDS.includes(began.kind)) continue;
    const at = timeMs(split.at);
    const fromX = Math.min(parent.x1, Math.max(parent.x0, scale && at !== null ? scale.x(at) : parent.x1));
    const lo = Math.min(fromX, child.x0);
    let track = trackEnds.findIndex((end) => end < lo - 2);
    if (track < 0) track = Math.min(trackEnds.length, HOOK_TRACKS - 1);
    trackEnds[track] = Math.max(fromX, child.x0);
    hooks.push({ key: child.bar.conversation_id, kind: began.kind, fromX, toX: child.x0, track });
  }

  return {
    plotPx, segs, bands, hooks, ordered: scale === null,
    items: items.map((item) => ({ item, y: item.x, labelTop: tops.get(item.key) ?? null })),
    ticks: scale ? rulerTicks(scale, plotPx) : [],
  };
}

export function stepColumn(column: Column, key: string | null, move: 'left' | 'right' | 'up' | 'down' | 'home' | 'end'): string | null {
  const keys = column.items.map((c) => c.item.key);
  if (keys.length === 0) return null;
  const i = key === null ? -1 : keys.indexOf(key);
  if (i < 0) return column.items.find((c) => c.item.kind === 'conversation' && c.item.bar.current)?.item.key ?? keys[0]!;
  if (move === 'home') return keys[0]!;
  if (move === 'end') return keys[keys.length - 1]!;
  return keys[Math.max(0, Math.min(keys.length - 1, i + (move === 'left' || move === 'up' ? -1 : 1)))]!;
}
