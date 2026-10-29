import type { TagTone } from '../../base/classes';
import type { Automation, RunCounts } from '../api';
import { isUnread, type UnreadState } from '../logic/feed';
import { lightOf } from '../logic/marks';
import { signalsOf } from '../logic/signals';
import type { RecentRun } from '../logic/types';

export const GROUP_CAP = 12;
export const FIND_AFTER = 20;

export type Tone = 'coral' | 'yellow' | 'green' | 'calm' | 'gray';

export function tagToneOf(tone: Tone): TagTone {
  return tone === 'coral' ? 'danger' : tone === 'yellow' ? 'warn' : tone === 'green' ? 'ok' : 'neutral';
}

export function isOften(cron: string): boolean {
  const f = String(cron ?? '').trim().split(/\s+/);
  return f.length === 5 && (f[1] === '*' || f[1] === '*/1');
}

export function showFind(count: number): boolean {
  return count > FIND_AFTER;
}

export function needsYou(run: Pick<RecentRun, 'status' | 'reason'>): boolean {
  return run.status === 'failed' || run.status === 'waiting_on_you' || (run.status === 'skipped' && run.reason !== 'scheduler_paused');
}

export function unreadNeeds(a: Pick<Automation, 'recent'>, state: UnreadState, now: number): number {
  return (a.recent ?? []).filter((r) => needsYou(r) && isUnread(r, state, now)).length;
}

export interface TileValues {
  active: number;
  total: number;
  next: { at: number; name: string } | null;
  needs: number;
  failed: number;
}

export function tileValues(rows: readonly Automation[], counts: RunCounts | null, state: UnreadState, now: number): TileValues {
  const on = rows.filter((a) => a.enabled);
  const next = on
    .filter((a) => a.next_fire_at != null)
    .sort((a, b) => a.next_fire_at! - b.next_fire_at!)[0];
  const newestNeeds = rows.filter((a) => {
    const last = a.recent?.[0];
    return !!last && needsYou(last) && isUnread(last, state, now);
  }).length;
  return {
    active: on.length,
    total: rows.length,
    next: next ? { at: next.next_fire_at!, name: next.name } : null,
    needs: Math.max(newestNeeds, counts?.counters.waiting_on_you.count ?? 0),
    failed: counts?.counters.failed_24h.count ?? 0,
  };
}

export interface CardTag {
  key: 'need_you' | 'last_failed' | 'needs_you' | 'skipped';
  n: number;
  tone: Tone;
}

export function cardTag(a: Pick<Automation, 'recent'>, enabled: boolean, paused: boolean, state: UnreadState, now: number): CardTag | null {
  if (!enabled || paused) return null;
  const n = unreadNeeds(a, state, now);
  const last = a.recent?.[0] ?? null;
  if (n > 1) return { key: 'need_you', n, tone: 'yellow' };
  if (last?.status === 'failed') return { key: 'last_failed', n: 0, tone: 'coral' };
  if (last?.status === 'waiting_on_you') return { key: 'needs_you', n: 0, tone: 'yellow' };
  if (last?.status === 'skipped' && last.reason !== 'scheduler_paused') return { key: 'skipped', n: 0, tone: 'gray' };
  return null;
}

export interface CardWord {
  key: 'off' | 'paused' | 'running' | 'failed' | 'needs_you' | 'skipped';
  tone: Tone;
}

export function cardWord(a: Pick<Automation, 'recent'>, enabled: boolean, paused: boolean): CardWord | null {
  if (!enabled) return { key: paused ? 'paused' : 'off', tone: 'calm' };
  if (paused) return { key: 'paused', tone: 'calm' };
  const light = lightOf(enabled, paused, signalsOf({ recent: a.recent ?? [], median_took_s: null, newest_output_empty: false }, enabled).last?.status ?? null);
  if (light.kind !== 'run') return null;
  switch (light.status) {
    case 'failed':
      return { key: 'failed', tone: 'coral' };
    case 'waiting_on_you':
      return { key: 'needs_you', tone: 'yellow' };
    case 'skipped':
      return { key: 'skipped', tone: 'calm' };
    default:
      return { key: 'running', tone: 'green' };
  }
}

export interface Columns {
  often: Automation[];
  slow: Automation[];
}

export function columns(rows: readonly Automation[]): Columns {
  return {
    often: rows.filter((a) => isOften(a.trigger.cron)),
    slow: rows.filter((a) => !isOften(a.trigger.cron)),
  };
}

export function capped<T>(rows: readonly T[], expanded: boolean): readonly T[] {
  return expanded ? rows : rows.slice(0, GROUP_CAP);
}
