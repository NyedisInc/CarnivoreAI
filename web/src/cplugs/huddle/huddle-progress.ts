
export const PHASES = ['queued', 'running', 'testing', 'installing', 'blocked', 'done'] as const;
export type Phase = (typeof PHASES)[number];

export interface ProgressLine {
  worker: string;
  phase: Phase;
  note: string;
  age_s: number;
  stale: boolean;
}

export const PHASE_COLOR: Record<Phase, string> = {
  queued: 'var(--oc-text-dim)',
  running: 'var(--oc-green)',
  testing: 'var(--oc-cyan)',
  installing: 'var(--oc-orange)',
  blocked: 'var(--oc-coral)',
  done: 'var(--oc-text-dim)',
};

export const CLIP = 60;

export const STALE_AFTER_S = 30 * 60;

export function clip(note: string, limit: number = CLIP): string {
  return note.length <= limit ? note : `${note.slice(0, limit - 1).trimEnd()}…`;
}

export function ageNow(line: ProgressLine, sinceReadMs: number): number {
  return line.age_s + Math.max(0, Math.floor(sinceReadMs / 1000));
}

export function isStale(line: ProgressLine, sinceReadMs: number): boolean {
  return line.stale || ageNow(line, sinceReadMs) >= STALE_AFTER_S;
}

export function elapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h >= 24) return `${Math.floor(h / 24)}d`;
  const rest = m % 60;
  return rest ? `${h}h ${rest}m` : `${h}h`;
}
