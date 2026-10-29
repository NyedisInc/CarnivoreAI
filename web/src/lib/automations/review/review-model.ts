import { isUnread, type UnreadState } from '../logic/feed';
import type { FeedRun } from '../logic/types';
import { bucketByDay, runTime, type Clock } from '../logic/words';

export type ReviewMode = 'review' | 'all';

export interface RunWord {
  key: 'done' | 'needs_you' | 'failed' | 'skipped' | 'running' | 'paused';
  tone: 'coral' | 'yellow' | 'green' | 'calm';
}

export interface ReviewDay {
  key: string;
  label: string;
  runs: FeedRun[];
}

export function needsYou(run: Pick<FeedRun, 'status' | 'reason'>): boolean {
  return run.status === 'failed' || run.status === 'waiting_on_you' || (run.status === 'skipped' && run.reason !== 'scheduler_paused');
}

export function runWord(run: Pick<FeedRun, 'status' | 'reason'>): RunWord {
  if (run.status === 'running' || run.status === 'claimed') return { key: 'running', tone: 'green' };
  if (run.status === 'failed') return { key: 'failed', tone: 'coral' };
  if (run.status === 'waiting_on_you') return { key: 'needs_you', tone: 'yellow' };
  if (run.status === 'skipped') return run.reason === 'scheduler_paused' ? { key: 'paused', tone: 'calm' } : { key: 'skipped', tone: 'yellow' };
  return { key: 'done', tone: 'calm' };
}

export function runLines(run: Pick<FeedRun, 'title' | 'summary'>, face: string): { title: string; summary: string } {
  const title = (run.title ?? '').trim();
  if (!title) return { title: face, summary: '' };
  return { title, summary: (run.summary ?? '').trim() };
}

export function listed(runs: readonly FeedRun[], mode: ReviewMode, state: UnreadState, now: number): FeedRun[] {
  return mode === 'all' ? [...runs] : runs.filter((run) => isUnread(run, state, now));
}

export function toReviewCount(runs: readonly FeedRun[], state: UnreadState, now: number): number {
  return runs.filter((run) => isUnread(run, state, now)).length;
}

export function dayGroups(runs: readonly FeedRun[], clock: Clock, now: number): ReviewDay[] {
  return bucketByDay(runs, runTime, clock, now, true).map((b) => ({ key: b.key, label: b.label, runs: b.items }));
}

export function modeForPressed(pressed: Partial<Record<string, boolean>>): ReviewMode | null {
  if (pressed.failed_24h) return 'all';
  if (pressed.waiting_on_you) return 'review';
  return null;
}
