import type { CounterId } from './types';
import { DAY, runTime } from './words';

export interface CounterRun {
  status: string;
  ended_at: number | null;
  started_at: number | null;
  slot_at: number | null;
  created_at?: number | null;
  report_bytes: number | null;
  output_empty: boolean | null;
}

export const COUNTER_IDS: readonly CounterId[] = [
  'succeeded_24h',
  'failed_24h',
  'succeeded_7d',
  'failed_7d',
  'skipped_7d',
  'produced_nothing_7d',
  'running',
  'waiting_on_you',
];

export function counterLabelKey(id: CounterId): string {
  return `automations.page.counter.${id}`;
}

/* waiting on you */
export function counterTone(id: CounterId, count: number): 'coral' | 'yellow' | null {
  if (count <= 0) return null;
  if (id === 'failed_24h' || id === 'failed_7d') return 'coral';
  if (id === 'waiting_on_you') return 'yellow';
  return null;
}

export function producedNothing(run: Pick<CounterRun, 'report_bytes' | 'output_empty'>): boolean {
  return (run.report_bytes ?? 0) === 0 || run.output_empty === true;
}

/* waiting on you */
export function counts(id: CounterId, run: CounterRun, now: number): boolean {
  const at = runTime(run);
  switch (id) {
    case 'succeeded_24h':
      return run.status === 'succeeded' && at >= now - DAY;
    case 'failed_24h':
      return run.status === 'failed' && at >= now - DAY;
    case 'succeeded_7d':
      return run.status === 'succeeded' && at >= now - 7 * DAY;
    case 'failed_7d':
      return run.status === 'failed' && at >= now - 7 * DAY;
    case 'skipped_7d':
      return run.status === 'skipped' && at >= now - 7 * DAY;
    case 'produced_nothing_7d':
      return run.status === 'succeeded' && at >= now - 7 * DAY && producedNothing(run);
    case 'running':
      return run.status === 'running' || run.status === 'claimed';
    case 'waiting_on_you':
      return run.status === 'waiting_on_you';
  }
}

export function countAll(runs: CounterRun[], now: number): Record<CounterId, number> {
  const out = {} as Record<CounterId, number>;
  for (const id of COUNTER_IDS) out[id] = runs.filter((r) => counts(id, r, now)).length;
  return out;
}

export function pressedIds(pressed: Partial<Record<CounterId, boolean>>): CounterId[] {
  return COUNTER_IDS.filter((id) => pressed[id]);
}
