import { COLUMNS, type CardColumn, type CardView } from '../../board-types';
import type { BoardLane } from '../../board-data.svelte';

export const BANDS = ['review', 'in_progress', 'todo'] as const;
export type Band = (typeof BANDS)[number];

export interface ListRow {
  card: CardView;
  laneName: string;
  companyName: string | null;
  depth: number;
}

export interface ListBand {
  band: Band;
  rows: ListRow[];
}

export interface CardEvent {
  at: number;
  kind: string;
  from_col: string;
  to_col: string;
  by: string;
  detail: string;
}

export interface Phase {
  phase: 'created' | 'started' | 'review' | 'done';
  column: CardColumn;
  reached: boolean;
  at: number | null;
}

export interface HistoryLine {
  key: string;
  who: Who;
  column: CardColumn;
  at: number;
  detail: string;
}

export type Who = { kind: 'you' } | { kind: 'agent'; id: number } | { kind: 'system'; name: string };

const RANK: Record<Band, number> = { review: 0, in_progress: 1, todo: 2 };

export function listBands(lanes: readonly BoardLane[]): ListBand[] {
  const byId = new Map<number, Omit<ListRow, 'depth'>>();
  const order: number[] = [];
  for (const lane of lanes) {
    for (const column of BANDS) {
      for (const card of lane.columns[column] ?? []) {
        const seen = byId.get(card.id);
        if (!seen) order.push(card.id);
        if (!seen || (seen.card.lane_role && !card.lane_role)) byId.set(card.id, { card, laneName: lane.name, companyName: lane.companyName });
      }
    }
  }
  const kids = new Map<number, number[]>();
  const roots: number[] = [];
  for (const id of order) {
    const parent = byId.get(id)!.card.parent;
    if (parent !== null && parent !== id && byId.has(parent)) kids.set(parent, [...(kids.get(parent) ?? []), id]);
    else roots.push(id);
  }
  const bandOf = (id: number): Band => byId.get(id)!.card.column as Band;
  for (const list of kids.values()) list.sort((a, b) => RANK[bandOf(a)] - RANK[bandOf(b)]);
  const placed = new Set<number>();
  const walk = (id: number, depth: number, into: ListRow[]): void => {
    if (placed.has(id)) return;
    placed.add(id);
    into.push({ ...byId.get(id)!, depth });
    for (const kid of kids.get(id) ?? []) walk(kid, depth + 1, into);
  };
  const rows: Record<Band, ListRow[]> = { review: [], in_progress: [], todo: [] };
  for (const id of roots) walk(id, 0, rows[bandOf(id)]);
  for (const id of order) if (!placed.has(id)) walk(id, 0, rows[bandOf(id)]);
  return BANDS.map((band) => ({ band, rows: rows[band] })).filter((b) => b.rows.length > 0);
}

/* the detail pane */
export interface FoundCard {
  card: CardView;
  laneName: string;
  companyName: string | null;
}

export function findCard(lanes: readonly BoardLane[], id: number | null): FoundCard | null {
  if (id === null) return null;
  let copy: FoundCard | null = null;
  for (const lane of lanes) {
    for (const column of COLUMNS) {
      const card = lane.columns[column]?.find((c) => c.id === id);
      if (card && !card.lane_role) return { card, laneName: lane.name, companyName: lane.companyName };
      if (card) copy ??= { card, laneName: lane.name, companyName: lane.companyName };
    }
  }
  return copy;
}

const PHASES: readonly [Phase['phase'], CardColumn][] = [['created', 'todo'], ['started', 'in_progress'], ['review', 'review'], ['done', 'done']];

function landed(event: CardEvent): CardColumn | '' {
  if ((COLUMNS as readonly string[]).includes(event.to_col)) return event.to_col as CardColumn;
  if (event.kind === 'started') return 'in_progress';
  if (event.kind === 'finished') return 'review';
  if (event.kind === 'done') return 'done';
  return '';
}

export function phases(card: CardView, events: readonly CardEvent[]): Phase[] {
  const at = COLUMNS.indexOf(card.column);
  const last: Partial<Record<CardColumn, number>> = {};
  for (const e of events) {
    const col = landed(e);
    if (col) last[col] = e.at;
    if (e.kind === 'created') last.todo = last.todo ?? e.at;
  }
  return PHASES.map(([phase, column]) => {
    const reached = COLUMNS.indexOf(column) <= at;
    let when = last[column] ?? null;
    if (phase === 'created') when = card.created_at ?? when;
    if (phase === 'started' && when === null) when = card.holder?.started_at ?? null;
    return { phase, column, reached, at: reached ? when : null };
  });
}

function quiet(e: CardEvent): boolean {
  return e.kind === 'handoff' || e.kind === 'refresh_asked' || (e.kind === 'moved' && e.from_col === e.to_col);
}

const KIND_COLUMN: Record<string, CardColumn> = {
  created: 'todo', released: 'todo', lapsed: 'todo', waiting_for_slot: 'todo', dealt: 'todo',
  started: 'in_progress', swapped: 'in_progress', paused: 'in_progress', resumed: 'in_progress', marked: 'in_progress',
  rejected: 'in_progress', sent_back: 'in_progress', validated: 'review', finished: 'review', rollup: 'review',
  accepted: 'done', done: 'done', promoted: 'in_progress', archived: 'todo', unarchived: 'todo', auto_promote: 'todo', noted: 'todo',
};

export function whoOf(by: string): Who {
  if (by === 'owner' || by === 'joe') return { kind: 'you' };
  const agent = /^agent:(\d+)$/.exec(by);
  if (agent) return { kind: 'agent', id: Number(agent[1]) };
  return { kind: 'system', name: by.replace(/_/g, ' ') };
}

export function historyLines(events: readonly CardEvent[]): HistoryLine[] {
  const out: HistoryLine[] = [];
  for (const e of events) {
    if (quiet(e)) continue;
    const column = landed(e) || KIND_COLUMN[e.kind] || 'todo';
    const key = `swarm.board.list.event.${e.kind in KIND_COLUMN || e.kind === 'deleted' ? e.kind : 'moved'}`;
    out.push({ key, who: whoOf(e.by), column, at: e.at, detail: e.detail });
  }
  return out.reverse();
}

export function stamp(at: number): string {
  const d = new Date(at * 1000);
  const two = (n: number) => String(n).padStart(2, '0');
  return `${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}
