import type { BoardLane } from '../../board-data.svelte';
import type { CardColumn, CardView } from '../../board-types';
import type { CardEventRow } from '../calendar/card-events.svelte';

export const SCALES = ['day', 'three', 'week'] as const;
export type TimelineScale = (typeof SCALES)[number];

const HOUR = 3600000;

export interface TimelineWindow {
  start: number;
  end: number;
  ticks: number[];
}

export function timelineWindow(scale: TimelineScale, nowMs: number): TimelineWindow {
  const d = new Date(nowMs);
  if (scale === 'day') {
    const end = new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours() + 1).getTime();
    const start = end - 12 * HOUR;
    return { start, end, ticks: Array.from({ length: 12 }, (_, i) => start + i * HOUR) };
  }
  const days = scale === 'three' ? 3 : 7;
  const step = scale === 'three' ? 6 : 24;
  const end = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime();
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1 - days).getTime();
  const ticks: number[] = [];
  for (let i = 0; i < (days * 24) / step; i++) {
    const t = new Date(start);
    t.setHours(i * step);
    ticks.push(t.getTime());
  }
  return { start, end, ticks };
}

export function pct(at: number, win: TimelineWindow): number {
  const p = ((at * 1000 - win.start) / (win.end - win.start)) * 100;
  return Math.max(0, Math.min(100, p));
}

export type SegmentKind = 'wait' | 'work' | 'unrecorded' | 'review';

export interface Segment {
  kind: SegmentKind;
  from: number;
  to: number;
}

export interface CardTrack {
  card: CardView;
  segments: Segment[];
  reviewAt: number | null;
  active: boolean;
  lastAt: number;
  sentBack: number;
  worker: number | null;
}

const KIND_OF: Record<string, SegmentKind | null> = { todo: 'wait', in_progress: 'work', review: 'review', done: null };

export function trackCard(card: CardView, events: readonly CardEventRow[], win: TimelineWindow, nowSec: number): CardTrack {
  const since = win.start / 1000;
  const until = Math.min(nowSec, win.end / 1000);
  const created = card.created_at >= since;
  const firstFrom = events.find((e) => e.from_col)?.from_col;
  const phases: { at: number; col: string }[] = [
    created ? { at: card.created_at, col: 'todo' } : { at: since, col: firstFrom || (events.length ? 'todo' : card.column) },
  ];
  let sentBack = 0;
  let lastAt = created ? card.created_at : 0;
  for (const e of events) {
    if (!e.to_col || e.at < since) continue;
    lastAt = Math.max(lastAt, e.at);
    if (e.from_col === 'review' && (e.to_col === 'in_progress' || e.to_col === 'todo')) sentBack++;
    if (e.to_col === phases[phases.length - 1]!.col) continue;
    phases.push({ at: Math.max(e.at, phases[phases.length - 1]!.at), col: e.to_col });
  }
  const segments: Segment[] = [];
  let reviewAt: number | null = null;
  for (let i = 0; i < phases.length; i++) {
    const p = phases[i]!;
    const kind0 = KIND_OF[p.col] ?? null;
    if (!kind0) break;
    const next = phases[i + 1];
    const kind: SegmentKind = kind0 === 'wait' && next && (next.col === 'review' || next.col === 'done') ? 'unrecorded' : kind0;
    if (kind === 'review' && i > 0) reviewAt = p.at;
    const from = Math.max(p.at, since);
    const to = Math.min(next ? next.at : until, until);
    if (to > from || (to === from && !next)) segments.push({ kind, from, to: Math.max(from, to) });
  }
  const live: CardColumn[] = ['in_progress', 'review'];
  const active = created || events.some((e) => e.at >= since) || live.includes(card.column);
  const worker = card.column === 'in_progress' && card.holder ? card.holder.agent_id : null;
  return { card, segments, reviewAt, active, lastAt, sentBack, worker };
}

export interface ParentBlock {
  parent: CardTrack;
  children: CardTrack[];
  workers: number[];
}

export interface TimelineGroup {
  lane: BoardLane;
  parents: ParentBlock[];
  loose: CardTrack[];
  workers: number[];
}

const COLUMN_ORDER: Record<CardColumn, number> = { in_progress: 0, review: 1, todo: 2, done: 3 };

export function buildGroups(lanes: readonly BoardLane[], events: readonly CardEventRow[], win: TimelineWindow, nowSec: number): TimelineGroup[] {
  const byCard = new Map<number, CardEventRow[]>();
  for (const e of events) {
    const list = byCard.get(e.item_id);
    if (list) list.push(e);
    else byCard.set(e.item_id, [e]);
  }
  const groups: TimelineGroup[] = [];
  for (const lane of lanes) {
    const cards = (['todo', 'in_progress', 'review', 'done'] as const).flatMap((c) => lane.columns[c]);
    const ids = new Set(cards.map((c) => c.id));
    const tracks = new Map(cards.map((c) => [c.id, trackCard(c, byCard.get(c.id) ?? [], win, nowSec)]));
    const kids = new Map<number, CardTrack[]>();
    for (const c of cards) {
      if (c.parent === null || !ids.has(c.parent)) continue;
      const list = kids.get(c.parent);
      if (list) list.push(tracks.get(c.id)!);
      else kids.set(c.parent, [tracks.get(c.id)!]);
    }
    const parents: ParentBlock[] = [];
    const placed = new Set<number>();
    for (const c of [...cards].sort((a, b) => a.id - b.id)) {
      const children = kids.get(c.id);
      const self = tracks.get(c.id)!;
      if (!children || placed.has(c.id)) continue;
      if (!self.active && !children.some((k) => k.active)) continue;
      children.sort((a, b) => a.card.id - b.card.id);
      const workers = [...new Set([self, ...children].map((k) => k.worker).filter((w): w is number => w !== null))];
      parents.push({ parent: self, children, workers });
      placed.add(c.id);
      for (const k of children) placed.add(k.card.id);
    }
    const loose = cards
      .map((c) => tracks.get(c.id)!)
      .filter((k) => k.active && !placed.has(k.card.id))
      .sort((a, b) => COLUMN_ORDER[a.card.column] - COLUMN_ORDER[b.card.column] || b.lastAt - a.lastAt || b.card.id - a.card.id);
    if (!parents.length && !loose.length) continue;
    const workers = [...new Set([...parents.flatMap((p) => p.workers), ...loose.map((k) => k.worker).filter((w): w is number => w !== null)])];
    groups.push({ lane, parents, loose, workers });
  }
  return groups;
}
