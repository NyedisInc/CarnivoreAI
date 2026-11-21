import { t } from '../i18n/index.svelte';
import type { JobView } from './jobs-api';

const CALLER_DONE = new Set(['here', 'done', 'failed', 'lost', 'stopped', 'refused']);
const HOST_LIVE = new Set(['preparing', 'running', 'parked']);
const KNOWN = new Set(['placing', 'here', 'waiting_approval', 'mirroring', 'starting', 'running', 'collecting', 'landing', 'done', 'failed',
  'lost', 'stopped', 'question', 'refused', 'preparing', 'exited', 'missing', 'parked']);
const TONE: Record<string, 'ok' | 'danger' | 'warn' | 'info' | 'neutral'> = {
  done: 'ok', exited: 'ok', failed: 'danger', lost: 'danger', refused: 'danger', missing: 'danger', question: 'warn', parked: 'warn', stopped: 'neutral', here: 'neutral',
};

export const WARM_PREFIX = 'warm-';

export function isJobId(id: string): boolean {
  return !id.startsWith(WARM_PREFIX);
}

export function isLive(job: Pick<JobView, 'side' | 'state'>): boolean {
  return job.side === 'host' ? HOST_LIVE.has(job.state) : !CALLER_DONE.has(job.state);
}

export function isWaiting(job: Pick<JobView, 'state' | 'question'>): boolean {
  return job.state === 'question' || job.state === 'parked' || !!job.question;
}

export function stateWord(state: string): string {
  return KNOWN.has(state) ? t(`pack.jobs.state.${state}`) : state;
}

export function stateTone(state: string): 'ok' | 'danger' | 'warn' | 'info' | 'neutral' {
  return TONE[state] ?? 'info';
}

function head(text: string | null, max = 140): string {
  const line = (text ?? '').split('\n', 1)[0]?.trim() ?? '';
  return line.length > max ? `${line.slice(0, max - 1)}...` : line;
}

export function jobHead(job: JobView): string {
  const own = job.body === 'agent' ? head(job.task_head) : head(job.command);
  if (own) return own;
  return t(job.body === 'agent' ? 'pack.jobs.head.agent' : 'pack.jobs.head.command');
}

export function jobWhere(job: JobView): string {
  return [job.computer, job.project_name].filter((part): part is string => !!part).join(' · ');
}

export function durationWords(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function clockWords(seconds: number): string {
  const d = new Date(seconds * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function whenWords(job: JobView): string {
  const from = job.started_at ?? job.created_at;
  if (!isLive(job)) return job.ended_at ? t('pack.jobs.ran', { time: durationWords(job.ended_at - from) }) : '';
  return t('pack.jobs.since', { time: clockWords(from) });
}
