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

export interface LoadReport {
  days: number;
  fleet_now: {
    aggregate: {
      online_machines: number;
      total_machines: number;
      fleet_cpu_pct: number | null;
      usable_free_cores: number;
      fleet_ram_pct: number | null;
      usable_free_ram_gb: number;
      active_jobs: number;
    } | null;
  };
  utilization_history: {
    idle_while_peer_pegged_minutes: number;
    pegged_minutes_total: number;
  };
  efficiency: {
    p50_overhead_s: number | null;
    p50_run_s: number | null;
    overhead_ratio: number | null;
  };
  guard_health: {
    funnel: Record<string, number>;
  };
}

export interface MetricsApi {
  read(days?: number): Promise<Metrics>;
  loadReport?(days?: number): Promise<LoadReport>;
}

export const metricsApi: MetricsApi = {
  read: (days = 7) => authFetch<Metrics>(`/pack/jobs/metrics?days=${days}`, { method: 'GET' }),
  loadReport: (days = 7) => authFetch<LoadReport>(`/pack/load/report?days=${days}`, { method: 'GET' }),
};
