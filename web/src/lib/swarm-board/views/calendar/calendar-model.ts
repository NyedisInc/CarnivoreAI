import type { BoardLane } from '../../board-data.svelte';
import type { CardEventRow } from './card-events.svelte';

export const SCALES = ['day', 'three', 'week'] as const;
export type CalendarScale = (typeof SCALES)[number];

export const KINDS = ['created', 'started', 'review', 'approved', 'sent_back'] as const;
export type CalendarKind = (typeof KINDS)[number];

export interface CalendarDay {
  start: number;
  end: number;
  date: Date;
  today: boolean;
  ahead: boolean;
}

export interface DayCell {
  counts: Record<CalendarKind, number>;
  hours: number[];
}

function midnight(ms: number, days = 0): number {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + days).getTime();
}

/* the day before yesterday */
export function calendarDays(scale: CalendarScale, nowMs: number): CalendarDay[] {
  const today = midnight(nowMs);
  const weekday = (new Date(today).getDay() + 6) % 7;
  const first = scale === 'day' ? 0 : scale === 'three' ? -2 : -weekday;
  const count = scale === 'day' ? 1 : scale === 'three' ? 3 : 7;
  const days: CalendarDay[] = [];
  for (let i = 0; i < count; i++) {
    const start = midnight(today, first + i);
    days.push({ start, end: midnight(start, 1), date: new Date(start), today: start === today, ahead: start > today });
  }
  return days;
}

export function eventKind(row: Pick<CardEventRow, 'kind' | 'from_col' | 'to_col'>): CalendarKind | null {
  if (row.kind === 'created') return 'created';
  if (row.kind === 'sent_back' || row.kind === 'rejected') return 'sent_back';
  if (row.to_col === row.from_col) return null;
  if (row.to_col === 'in_progress') return 'started';
  if (row.to_col === 'review') return 'review';
  if (row.to_col === 'done') return 'approved';
  return null;
}

export function emptyCell(): DayCell {
  return { counts: { created: 0, started: 0, review: 0, approved: 0, sent_back: 0 }, hours: new Array(24).fill(0) };
}

export function bucketEvents(rows: readonly CardEventRow[], days: readonly CalendarDay[], laneOf: (row: CardEventRow) => string | null,
  keep: (row: CardEventRow) => boolean): Map<string, DayCell[]> {
  const out = new Map<string, DayCell[]>();
  const seen = new Set<string>();
  for (const row of rows) {
    const kind = eventKind(row);
    if (!kind || !keep(row)) continue;
    const lane = laneOf(row);
    if (lane === null) continue;
    const ms = row.at * 1000;
    const index = days.findIndex((d) => ms >= d.start && ms < d.end);
    if (index < 0) continue;
    let cells = out.get(lane);
    if (!cells) {
      cells = days.map(() => emptyCell());
      out.set(lane, cells);
    }
    const cell = cells[index];
    if (!cell) continue;
    const hour = new Date(ms).getHours();
    cell.hours[hour] = (cell.hours[hour] ?? 0) + 1;
    const key = `${lane}|${index}|${kind}|${row.item_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    cell.counts[kind] += 1;
  }
  return out;
}

export function facesByDay(lane: Pick<BoardLane, 'columns'>, days: readonly CalendarDay[]): number[][] {
  const out = days.map(() => [] as number[]);
  for (const card of lane.columns.in_progress ?? []) {
    const at = card.holder ? (card.holder.started_at ?? card.holder.since) : null;
    if (!card.holder || at === null) continue;
    const index = days.findIndex((d) => at * 1000 >= d.start && at * 1000 < d.end);
    const day = out[index];
    if (day && !day.includes(card.holder.agent_id)) day.push(card.holder.agent_id);
  }
  return out;
}

export function dayFraction(day: CalendarDay, nowMs: number): number {
  return Math.min(1, Math.max(0, (nowMs - day.start) / (day.end - day.start)));
}

export function groupLanes<L extends Pick<BoardLane, 'companyName'>>(lanes: readonly L[]): { company: string | null; lanes: L[] }[] {
  const groups: { company: string | null; lanes: L[] }[] = [];
  for (const lane of lanes) {
    const group = groups.find((g) => g.company === lane.companyName);
    if (group) group.lanes.push(lane);
    else groups.push({ company: lane.companyName, lanes: [lane] });
  }
  return groups;
}
