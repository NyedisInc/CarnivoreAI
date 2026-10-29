
export interface CoverageInput {
  latest?: string | null;
  freshness_seconds?: number | null;
  minute_rows?: number;
  quality_rows?: number;
  unknown_cost_rows?: number;
  disabled_spans?: unknown[];
  sources?: { status: string; quality: string; count: number }[];
  backfill?: Record<string, number>;
  db_bytes?: number | null;
  collector?: {
    state?: string;
    last_success?: number | null;
    backfill_running?: boolean;
    collector?: { known_sources?: number; pending_sources?: number; initial_pending_sources?: number; backfill_complete?: boolean };
  } | null;
}

const KNOWN_STATES = ['ok', 'pending', 'error', 'disabled', 'stopping'];

export const COLLECTOR_STALE_SECONDS = 45;

export type HealthTone = 'ok' | 'warn' | 'bad' | 'unknown';

export interface HealthModel {
  state: string | null;
  tone: HealthTone;
  passAgeSeconds: number | null;
  freshnessSeconds: number | null;
  pendingSources: number | null;
  knownSources: number | null;
  replaying: boolean | null;
  missingSources: number | null;
  qualityRows: number | null;
  unknownCostRows: number | null;
  dbBytes: number | null;
}

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

export function healthModel(coverage: CoverageInput | null, nowSeconds: number): HealthModel {
  const collector = coverage?.collector ?? null;
  const lastPass = num(collector?.last_success);
  const passAgeSeconds = lastPass === null ? null : Math.max(0, Math.round(nowSeconds - lastPass));
  const reported = typeof collector?.state === 'string' && KNOWN_STATES.includes(collector.state) ? collector.state : null;
  const stale = reported === 'ok' && passAgeSeconds !== null && passAgeSeconds > COLLECTOR_STALE_SECONDS;
  const state = stale ? 'stale' : reported;
  const tone: HealthTone = state === null ? 'unknown' : state === 'ok' ? 'ok' : state === 'error' || state === 'stale' ? 'bad' : 'warn';
  const progress = collector?.collector;
  return {
    state, tone, passAgeSeconds, freshnessSeconds: num(coverage?.freshness_seconds),
    pendingSources: num(progress?.pending_sources), knownSources: num(progress?.known_sources),
    replaying: typeof collector?.backfill_running === 'boolean' ? collector.backfill_running : null,
    missingSources: coverage?.sources ? coverage.sources.filter((row) => row.status === 'missing').reduce((sum, row) => sum + row.count, 0) : null,
    qualityRows: num(coverage?.quality_rows), unknownCostRows: num(coverage?.unknown_cost_rows), dbBytes: num(coverage?.db_bytes),
  };
}

export function scaleBytes(bytes: number): { unit: 'kb' | 'mb' | 'gb'; value: number } {
  const steps: [number, 'gb' | 'mb' | 'kb'][] = [[1024 ** 3, 'gb'], [1024 ** 2, 'mb']];
  for (const [size, unit] of steps) if (bytes >= size) return { unit, value: Math.round(bytes / size * 10) / 10 };
  return { unit: 'kb', value: Math.round(bytes / 1024 * 10) / 10 };
}
