import { authFetch } from '../../opscenter/api/auth.svelte';

export interface MetricsR3 {
  window_days: number;
  remote_minutes: number;
  local_minutes: number;
  share: number | null;
}

export interface MetricsP3 {
  window_days: number;
  misses: number;
  delegate_calls: number;
  share: number | null;
  threshold: number;
  over: boolean;
  enough_data: boolean;
}

export interface Metrics {
  days: number;
  p3: MetricsP3;
  r3: MetricsR3;
  load: { hours: unknown[] };
}

export interface MetricsApi {
  read(days?: number): Promise<Metrics>;
}

export const metricsApi: MetricsApi = {
  read: (days = 7) => authFetch<Metrics>(`/pack/jobs/metrics?days=${days}`, { method: 'GET' }),
};
