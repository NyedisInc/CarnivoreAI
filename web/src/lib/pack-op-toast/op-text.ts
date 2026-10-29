import { t } from '../i18n/index.svelte';
import { reasonText } from '../send-to/send-api';

export interface PackOp {
  id: string;
  kind: 'session' | 'project' | 'company';
  direction: 'out' | 'in';
  name: string | null;
  machine: string | null;
  mode: 'move' | 'copy' | 'fresh' | null;
  state: string;
  step: string | null;
  steps: string[];
  error_code: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  session_uuid: string | null;
  target_session_uuid: string | null;
  claude_session_uuid: string | null;
  wait_until: string | null;
  waiting_on: string | null;
  agents: number | null;
  shells: number | null;
  woken?: number | null;
  wake_failed?: { name: string; reason: string }[] | null;
  told?: number | null;
  continue_failed?: { name: string; reason: string }[] | null;
  running: boolean;
  interrupted: boolean;
  cancellable: boolean;
  cancel_blocked: string | null;
  progress?: OpProgress | null;
}

export interface OpProgress {
  step: string | null;
  bytes_done: number | null;
  bytes_total: number | null;
  rate: number | null;
  eta_s: number | null;
  log: { at: number; step: string | null; text: string }[];
}

export type OpPhase = 'running' | 'done' | 'failed' | 'canceled';

export function phaseOf(op: PackOp): OpPhase {
  if (op.running) return 'running';
  if (op.error_code === 'cancelled' || op.error_code === 'interrupted') return 'canceled';
  return op.state === 'failed' ? 'failed' : 'done';
}

function variant(op: PackOp): string {
  return op.direction === 'in' ? 'in' : op.kind === 'session' ? op.mode ?? 'move' : op.kind;
}

function params(op: PackOp): Record<string, string> {
  return { name: op.name || t('pack.op.label'), machine: op.machine || '' };
}

export function headline(op: PackOp): string {
  const phase = phaseOf(op);
  if (phase === 'running') return t(`pack.op.running.${variant(op)}`, params(op));
  if (phase === 'done') return t(`pack.op.done.${variant(op)}`, params(op));
  return t(op.direction === 'in' ? 'pack.op.failed.in' : 'pack.op.failed', params(op));
}

export function stepLine(op: PackOp): string {
  if (!op.running) return '';
  if (op.interrupted) return t('pack.op.stuck');
  const projectStep = op.kind !== 'session' && (op.step === 'code' || op.step === 'interrupt' || op.step === 'wait' || op.step === 'sleep' || op.step === 'wake' || op.step === 'continue');
  const key = `pack.op.step.${op.step ?? 'unknown'}${projectStep ? '_project' : ''}`;
  const text = t(key, { ...params(op), count: op.step === 'interrupt' || op.step === 'wait' || op.step === 'wake' || op.step === 'continue' ? op.agents ?? 0 : op.shells ?? 0 });
  const base = text === key ? t('pack.op.step.unknown') : text;
  const line = op.step === 'wait' && op.waiting_on ? `${base} ${op.waiting_on}.` : base;
  const until = op.step === 'wait' && op.wait_until ? new Date(op.wait_until) : null;
  return until && !Number.isNaN(until.getTime())
    ? `${line} ${t('pack.op.wait_until', { time: until.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase() })}` : line;
}

export function stepCount(op: PackOp): string {
  const at = op.step ? op.steps.indexOf(op.step) : -1;
  return op.running && at >= 0 ? t('pack.op.step_count', { n: at + 1, total: op.steps.length }) : '';
}

function wakeLine(op: PackOp): string {
  if (op.woken == null) return '';
  const failed = op.wake_failed ?? [];
  const started = t('pack.op.woken', { count: op.woken, machine: op.machine || '' });
  return failed.length === 0 ? started : `${started} ${failed.map((f) => t('pack.op.wake_failed', { name: f.name, reason: f.reason })).join(' ')}`;
}

function continueLine(op: PackOp): string {
  if (op.told == null) return '';
  const failed = op.continue_failed ?? [];
  const told = op.told > 0 ? t('pack.op.told', { count: op.told, machine: op.machine || '' }) : '';
  return [told, ...failed.map((f) => t('pack.op.continue_failed', { name: f.name, reason: f.reason }))].filter(Boolean).join(' ');
}

export function outcomeLine(op: PackOp): string {
  const phase = phaseOf(op);
  if (phase === 'canceled') return t(op.error_code === 'interrupted' ? 'pack.op.interrupted' : 'pack.op.cancelled', params(op));
  if (phase === 'done') return [wakeLine(op), continueLine(op)].filter(Boolean).join(' ');
  if (phase !== 'failed') return '';
  return op.error || reasonText(op.error_code);
}

export function elapsed(start: string, end: string | null, now: number): string {
  const from = Date.parse(start);
  const to = end ? Date.parse(end) : now;
  if (Number.isNaN(from) || Number.isNaN(to)) return '';
  const total = Math.max(0, Math.floor((to - from) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

export function sizeText(bytes: number): string {
  const units = ['b', 'kb', 'mb', 'gb'];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${i === 0 ? n : n.toFixed(1)} ${units[i]}`;
}

export function barFraction(op: PackOp): number | null {
  const at = op.step ? op.steps.indexOf(op.step) : -1;
  if (!op.running || at < 0 || op.steps.length === 0) return null;
  const p = op.progress;
  const share = p && p.step === op.step && p.bytes_total ? Math.min(0.99, (p.bytes_done ?? 0) / p.bytes_total) : 0;
  return (at + share) / op.steps.length;
}

export function bytesLine(op: PackOp): string {
  const p = op.progress;
  if (!op.running || !p || p.step !== op.step || !p.bytes_total) return '';
  const base = t('pack.op.bytes', { done: sizeText(p.bytes_done ?? 0), total: sizeText(p.bytes_total) });
  return p.rate ? `${base}, ${t('pack.op.rate', { rate: sizeText(p.rate) })}` : base;
}

export function etaLine(op: PackOp): string {
  const s = op.running && op.progress?.step === op.step ? op.progress?.eta_s : null;
  if (s == null) return '';
  return s >= 90 ? t('pack.op.eta_min', { n: Math.round(s / 60) }) : t('pack.op.eta_sec', { n: Math.max(1, s) });
}

export function logLine(l: { at: number; step: string | null; text: string }): string {
  const time = new Date(l.at * 1000).toLocaleTimeString([], { hour12: false });
  return `${time} ${l.step ? l.step + ' ' : ''}${l.text}`;
}
