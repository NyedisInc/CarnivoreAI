import { parseServerTime } from '../lib/format';

export interface RunwayWindow { kind: string; label: string; used_pct: number; resets_at: string | null; window_seconds?: number | null }
export interface RunwayAccount { id: string; name: string; credential_state?: string; windows: readonly RunwayWindow[] }
export interface QuotaSeries { key: string; points: readonly { time: string; value: number | null }[] }

export const MIN_SPAN_SECONDS = 300;

export type RunwayVerdict = 'hits_first' | 'resets_first' | 'idle' | 'full' | 'unknown';

export interface RunwayRow {
  id: string;
  name: string;
  window: RunwayWindow | null;
  usedPct: number | null;
  resetSeconds: number | null;
  burnPerHour: number | null;
  toLimitSeconds: number | null;
  verdict: RunwayVerdict;
}

export function burnPerHour(points: readonly { time: string; value: number | null }[]): number | null {
  const known = points.map((p) => ({ at: parseServerTime(p.time), value: p.value }))
    .filter((p): p is { at: number; value: number } => Number.isFinite(p.at) && typeof p.value === 'number' && Number.isFinite(p.value));
  let start = 0;
  for (let i = 1; i < known.length; i++) if (known[i]!.value < known[i - 1]!.value - 1) start = i;
  const run = known.slice(start);
  if (run.length < 2) return null;
  const first = run[0]!;
  const last = run[run.length - 1]!;
  const seconds = (last.at - first.at) / 1000;
  if (seconds < MIN_SPAN_SECONDS) return null;
  return Math.max(0, ((last.value - first.value) / seconds) * 3600);
}

export function runwayModel(accounts: readonly RunwayAccount[], series: readonly QuotaSeries[], kind: string | null, now: number): RunwayRow[] {
  return accounts.map((account) => {
    const window = (kind ? account.windows.find((item) => item.kind === kind) : null)
      ?? account.windows.reduce<RunwayWindow | null>((worst, item) => (!worst || item.used_pct > worst.used_pct ? item : worst), null);
    const base = { id: account.id, name: account.name, window, usedPct: window?.used_pct ?? null, resetSeconds: null as number | null, burnPerHour: null as number | null, toLimitSeconds: null as number | null };
    if (!window || !Number.isFinite(window.used_pct)) return { ...base, verdict: 'unknown' as const };
    const reset = window.resets_at ? parseServerTime(window.resets_at) : Number.NaN;
    const resetSeconds = Number.isFinite(reset) ? Math.max(0, Math.round((reset - now) / 1000)) : null;
    const burn = burnPerHour(series.find((item) => item.key === account.id)?.points ?? []);
    const row = { ...base, resetSeconds, burnPerHour: burn };
    if (window.used_pct >= 100) return { ...row, toLimitSeconds: 0, verdict: 'full' as const };
    if (burn === null || resetSeconds === null) return { ...row, verdict: 'unknown' as const };
    if (burn <= 0) return { ...row, verdict: 'idle' as const };
    const toLimitSeconds = Math.round(((100 - window.used_pct) / burn) * 3600);
    return { ...row, toLimitSeconds, verdict: toLimitSeconds < resetSeconds ? 'hits_first' as const : 'resets_first' as const };
  });
}

const RANK: Record<RunwayVerdict, number> = { full: 0, hits_first: 1, resets_first: 2, idle: 3, unknown: 4 };

export function byUrgency(rows: readonly RunwayRow[]): RunwayRow[] {
  return rows.map((row, index) => ({ row, index }))
    .sort((a, b) => RANK[a.row.verdict] - RANK[b.row.verdict]
      || (a.row.verdict === 'hits_first' ? (a.row.toLimitSeconds ?? 0) - (b.row.toLimitSeconds ?? 0) : 0) || a.index - b.index)
    .map((item) => item.row);
}
