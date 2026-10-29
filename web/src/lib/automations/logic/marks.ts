
export interface MarkPart {
  tag: 'rect' | 'path';
  attrs: Record<string, string>;
}

export type MarkName = 'succeeded' | 'failed' | 'skipped' | 'waiting_on_you' | 'running' | 'claimed' | 'future' | 'neutral';

const STROKE = { fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5' };

export const RUN_MARKS: Record<MarkName, MarkPart[]> = {
  succeeded: [{ tag: 'rect', attrs: { x: '2', y: '2', width: '10', height: '10', fill: 'currentColor' } }],
  failed: [
    { tag: 'rect', attrs: { x: '2.5', y: '2.5', width: '9', height: '9', ...STROKE } },
    { tag: 'path', attrs: { d: 'M1.5 12.5 12.5 1.5', stroke: 'currentColor', 'stroke-width': '1.5' } },
  ],
  skipped: [{ tag: 'path', attrs: { d: 'M5.5 2.5h-3v9h9v-9h-3', ...STROKE } }],
  waiting_on_you: [{ tag: 'path', attrs: { d: 'M7 1 13 7 7 13 1 7Z', fill: 'currentColor' } }],
  running: [{ tag: 'rect', attrs: { x: '2.5', y: '2.5', width: '9', height: '9', ...STROKE, 'stroke-dasharray': '5 3' } }],
  claimed: [{ tag: 'rect', attrs: { x: '2.5', y: '2.5', width: '9', height: '9', ...STROKE } }],
  future: [{ tag: 'path', attrs: { d: 'M7 2v10', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-dasharray': '2 2' } }],
  neutral: [{ tag: 'path', attrs: { d: 'M3 7h8', stroke: 'currentColor', 'stroke-width': '1.5' } }],
};

export function runMarkName(status: string): MarkName {
  return status in RUN_MARKS ? (status as MarkName) : 'claimed';
}

export type WordKind = 'ok' | 'warn' | 'fail';

const WORDS_OK = new Set(['ok', 'pass', 'passed', 'healthy']);
const WORDS_WARN = new Set(['warn', 'raised']);
const WORDS_FAIL = new Set(['fail', 'failed', 'error']);

export function wordKind(value: unknown): WordKind | null {
  if (typeof value !== 'string') return null;
  const w = value.trim().toLowerCase();
  if (WORDS_OK.has(w)) return 'ok';
  if (WORDS_WARN.has(w)) return 'warn';
  if (WORDS_FAIL.has(w)) return 'fail';
  return null;
}

export function wordMark(value: unknown): MarkName | null {
  const kind = wordKind(value);
  const w = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (!kind && (w === 'info' || w === 'none')) return 'neutral';
  if (!kind) return null;
  return kind === 'ok' ? 'succeeded' : kind === 'warn' ? 'skipped' : 'failed';
}

export type Light = { kind: 'off' } | { kind: 'ok' } | { kind: 'run'; status: string };

export function lightOf(enabled: boolean, schedulerPaused: boolean, newestStatus: string | null): Light {
  if (!enabled || schedulerPaused) return { kind: 'off' };
  if (newestStatus && ['skipped', 'failed', 'running', 'waiting_on_you', 'claimed'].includes(newestStatus)) {
    return { kind: 'run', status: newestStatus };
  }
  return { kind: 'ok' };
}
